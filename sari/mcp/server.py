import json
import os
import sys
import threading
import queue
import concurrent.futures
import socket
import time
from pathlib import Path
from typing import Any, Dict, Optional, List
from sari.mcp.workspace_registry import Registry
from sari.core.workspace import WorkspaceManager
from sari.core.settings import settings
from sari.mcp.policies import PolicyEngine
from sari.mcp.middleware import PolicyMiddleware, run_middlewares
from sari.mcp.tools.registry import ToolContext, build_default_registry
from sari.mcp.telemetry import TelemetryLogger
from sari.mcp.transport import McpTransport

try:
    import orjson as _orjson
except Exception:
    _orjson = None

class JsonRpcException(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data

def _json_dumps(obj: Any) -> str:
    if _orjson:
        return _orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj)


MAX_MESSAGE_SIZE = 10 * 1024 * 1024 # 10MB

class LocalSearchMCPServer:
    """
    Modernized MCP Server for Sari.
    Delegates workspace management to WorkspaceRegistry.
    """
    PROTOCOL_VERSION = "2025-11-25"
    SUPPORTED_VERSIONS = {"2024-11-05", "2025-03-26", "2025-11-25"}
    SERVER_NAME = "sari"
    SERVER_VERSION = settings.VERSION
    _SENSITIVE_KEYS = ("token", "secret", "password", "api_key", "apikey", "authorization", "cookie", "key")

    def __init__(self, workspace_root: str, cfg: Any = None, db: Any = None, indexer: Any = None):
        self.workspace_root = workspace_root
        # Keep optional injected handles for backward compatibility with older callers.
        self._injected_cfg = cfg
        self._injected_db = db
        self._injected_indexer = indexer
        self.registry = Registry.get_instance()
        self.policy_engine = PolicyEngine(mode=settings.SEARCH_FIRST_MODE)
        self.logger = TelemetryLogger(WorkspaceManager.get_global_log_dir())
        self._tool_registry = build_default_registry()
        self._middlewares = [PolicyMiddleware(self.policy_engine)]
        # Add maxsize to prevent memory bloat under heavy load
        self._req_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=settings.get_int("MCP_QUEUE_SIZE", 1000))
        self._stop = threading.Event()
        self._stdout_lock = threading.Lock()
        self.transport = None
        self._session = None
        self._session_acquired = False
        self._daemon_lock = threading.Lock()
        self._daemon_channels_lock = threading.Lock()
        self._daemon_channels: Dict[int, Any] = {}
        self._debug_enabled = (os.environ.get("SARI_MCP_DEBUG_LOG", "").strip().lower() in {"1", "true", "yes", "on"})
        
        # Ownership Enforcment: Check if daemon is active for this workspace
        self._proxy_to_daemon = False
        self._daemon_sock = None
        if not os.environ.get("SARI_STANDALONE_ONLY") and not self._injected_db:
            try:
                from sari.core.server_registry import ServerRegistry
                inst = ServerRegistry().resolve_workspace_daemon(self.workspace_root)
                if inst and inst.get("host") and inst.get("port"):
                    self._log_debug(f"Daemon detected at {inst['host']}:{inst['port']}. Switching to thin-adapter mode.")
                    self._proxy_to_daemon = True
                    self._daemon_address = (inst["host"], int(inst["port"]))
            except Exception as e:
                self._log_debug(f"Failed to check daemon registry: {e}")

        max_workers = int(os.environ.get("SARI_MCP_WORKERS", "4") or 4)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        root_uri = params.get("rootUri") or params.get("rootPath")
        workspace_folders = params.get("workspaceFolders", [])
        
        # Primary workspace selection strategy:
        # 1. Use rootUri if provided.
        # 2. Otherwise, use the first workspaceFolder if available.
        # 3. Fallback to CWD (handled in resolve_workspace_root).
        target_uri = root_uri
        if not target_uri and workspace_folders:
            target_uri = workspace_folders[0].get("uri")

        if target_uri:
            # Update workspace if provided by client
            self.workspace_root = WorkspaceManager.resolve_workspace_root(root_uri=target_uri)
        
        # Negotiate Protocol Version
        client_version = params.get("protocolVersion")
        if client_version and client_version not in self.SUPPORTED_VERSIONS:
            raise JsonRpcException(
                -32602, 
                "Unsupported protocol version", 
                data={"supported": sorted(list(self.SUPPORTED_VERSIONS))}
            )
        
        # Echo client version if provided, otherwise fallback to server default
        negotiated_version = client_version if client_version else self.PROTOCOL_VERSION
            
        return {
            "protocolVersion": negotiated_version,
            "serverInfo": {"name": self.SERVER_NAME, "version": self.SERVER_VERSION},
            # Be explicit about supported capability surfaces so strict MCP
            # clients can finish startup without probing unknown methods.
            "capabilities": {
                "tools": {"listChanged": False},
                "prompts": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
        }

    def handle_initialized(self, params: Dict[str, Any]) -> None:
        """Called by client after initialize response is received."""
        # Optional: Start background tasks here if needed
        pass

    def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = params.get("name")
        args = params.get("arguments", {})
        cfg = self._injected_cfg

        if self._injected_db is not None and self._injected_indexer is not None:
            db = self._injected_db
            indexer = self._injected_indexer
            roots = list(getattr(cfg, "workspace_roots", []) or [self.workspace_root])
        else:
            if self._session is None:
                self._session = self.registry.get_or_create(self.workspace_root)
                self._session_acquired = True
            session = self._session
            db = getattr(session, "db", None)
            indexer = getattr(session, "indexer", None)
            cfg_data = getattr(session, "config_data", {}) or {}
            roots = list(cfg_data.get("workspace_roots", [self.workspace_root]))
            if db is None:
                raise JsonRpcException(-32000, "tools/call failed: session.db is unavailable")

        ctx = ToolContext(
            db=db,
            engine=getattr(db, "engine", None),
            indexer=indexer,
            roots=roots,
            cfg=cfg,
            logger=self.logger,
            workspace_root=self.workspace_root,
            server_version=self.SERVER_VERSION, 
            policy_engine=self.policy_engine
        )

        return run_middlewares(
            tool_name,
            ctx,
            args,
            self._middlewares,
            lambda: self._tool_registry.execute(tool_name, ctx, args),
        )

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self._proxy_to_daemon:
            return self._forward_to_daemon(request)

        method, params, msg_id = request.get("method"), request.get("params", {}), request.get("id")
        if msg_id is None: return None # Ignore notifications for now
        
        try:
            if method == "initialize": result = self.handle_initialize(params)
            elif method == "tools/list": result = {"tools": self._tool_registry.list_tools()}
            elif method == "prompts/list": result = {"prompts": []}
            elif method == "resources/list": result = {"resources": []}
            elif method == "resources/templates/list": result = {"resourceTemplates": []}
            elif method == "tools/call": result = self.handle_tools_call(params)
            elif method in {"initialized", "notifications/initialized"}: result = {}
            elif method == "ping": result = {}
            else: return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except JsonRpcException as e:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": e.code, "message": e.message, "data": e.data}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(e)}}

    def _forward_to_daemon(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Forward MCP request to the TCP daemon and return response."""
        tid = threading.get_ident()
        try:
            conn, f = self._ensure_daemon_connection(tid)
            try:
                return self._forward_over_open_socket(request, conn, f)
            except Exception:
                # Retry once with a fresh per-thread connection.
                self._close_daemon_connection(tid)
                conn, f = self._ensure_daemon_connection(tid)
                return self._forward_over_open_socket(request, conn, f)
        except Exception as e:
            msg_id = request.get("id")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32002,
                    "message": f"Failed to forward to daemon: {e}. Try 'sari daemon start'."
                }
            } if msg_id is not None else None

    def _ensure_daemon_connection(self, tid: int):
        with self._daemon_channels_lock:
            ch = self._daemon_channels.get(tid)
            if ch is not None:
                return ch
        conn = socket.create_connection(self._daemon_address, timeout=settings.DAEMON_TIMEOUT_SEC)
        f = conn.makefile("rb")
        with self._daemon_channels_lock:
            self._daemon_channels[tid] = (conn, f)
        return conn, f

    def _close_daemon_connection(self, tid: Optional[int] = None) -> None:
        if tid is None:
            self._close_all_daemon_connections()
            return
        with self._daemon_channels_lock:
            ch = self._daemon_channels.pop(tid, None)
        if not ch:
            return
        conn, f = ch
        try:
            f.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    def _close_all_daemon_connections(self) -> None:
        with self._daemon_channels_lock:
            items = list(self._daemon_channels.items())
            self._daemon_channels.clear()
        for _tid, (conn, f) in items:
            try:
                f.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _forward_over_open_socket(self, request: Dict[str, Any], conn: Any, f: Any) -> Optional[Dict[str, Any]]:
        body = json.dumps(request).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        conn.sendall(header + body)

        headers: Dict[bytes, bytes] = {}
        while True:
            line = f.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                break
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower()] = v.strip()

        content_length = int(headers.get(b"content-length", b"0"))
        if content_length <= 0:
            return None
        resp_body = f.read(content_length)
        if not resp_body:
            return None
        return json.loads(resp_body.decode("utf-8"))

    def run(self) -> None:
        """Standard MCP JSON-RPC loop with encapsulated transport."""
        self._log_debug("Sari MCP Server starting run loop...")
        
        if not self.transport:
            input_stream = getattr(sys.stdin, "buffer", sys.stdin)
            original_stdout = getattr(self, "_original_stdout", None)
            output_stream = getattr(original_stdout, "buffer", None) if original_stdout is not None else None
            if output_stream is None:
                output_stream = getattr(sys.stdout, "buffer", sys.stdout)
            self.transport = McpTransport(input_stream, output_stream)

        try:
            while not self._stop.is_set():
                res = self.transport.read_message()
                if res is None:
                    break
                
                req, mode = res
                self._log_debug_request(mode, req)
                
                # Attach metadata for response framing matching
                req["_sari_framing_mode"] = mode
                
                try:
                    # Async dispatch to avoid blocking the read loop
                    self._req_queue.put(req)
                except Exception as e:
                    self._log_debug(f"ERROR putting req to queue: {e}")
        except Exception as e:
            self._log_debug(f"CRITICAL in run loop: {e}")
        finally:
            self._drain_pending_requests()
            self._log_debug("Sari MCP Server shutting down...")
            self.shutdown()

    def shutdown(self) -> None:
        """Graceful shutdown of all resources."""
        if self._stop.is_set():
            return
        self._stop.set()
        
        # 1. Stop processing new requests
        try:
            self._executor.shutdown(wait=True, cancel_futures=False)
        except Exception:
            pass
            
        # 2. Cleanup all workspace resources (DB, Engine)
        try:
            self.registry.shutdown_all()
        except Exception:
            pass
        try:
            if self.transport and hasattr(self.transport, "close"):
                self.transport.close()
        except Exception:
            pass
        try:
            if self.logger and hasattr(self.logger, "stop"):
                self.logger.stop()
        except Exception:
            pass
        try:
            self._close_daemon_connection()
        except Exception:
            pass
        try:
            if self._session_acquired:
                self.registry.release(self.workspace_root)
                self._session_acquired = False
                self._session = None
        except Exception:
            pass

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                req = self._req_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._executor.submit(self._handle_and_respond, req)
            except Exception:
                pass
            finally:
                try:
                    self._req_queue.task_done()
                except Exception:
                    pass

    def _drain_pending_requests(self) -> None:
        while True:
            try:
                req = self._req_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_and_respond(req)
            finally:
                try:
                    self._req_queue.task_done()
                except Exception:
                    pass

    def _handle_and_respond(self, req: Dict[str, Any]) -> None:
        try:
            resp = self.handle_request(req)
            if resp:
                mode = req.get("_sari_framing_mode", "content-length")
                self._log_debug_response(mode, resp)
                if self.transport is None:
                    raise RuntimeError("transport is not initialized")
                # Serialize writes to stdout transport to avoid frame interleaving.
                with self._stdout_lock:
                    self.transport.write_message(resp, mode=mode)
        except Exception as e:
            self._log_debug(f"ERROR in _handle_and_respond: {e}")

    def _log_debug(self, message: str) -> None:
        """Log MCP traffic to a dedicated debug file."""
        if not self._debug_enabled:
            return
        try:
            log_path = Path.home() / ".local" / "share" / "sari" / "mcp_debug.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass

    def _sanitize_value(self, value: Any, key: str = "") -> Any:
        key_l = (key or "").lower()
        if any(s in key_l for s in self._SENSITIVE_KEYS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {k: self._sanitize_value(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_value(v, key) for v in value[:20]]
        if isinstance(value, str):
            if key_l in {"content", "text", "source", "snippet", "body"}:
                return f"[REDACTED_TEXT len={len(value)}]"
            if len(value) > 200:
                return value[:120] + "...[truncated]"
            return value
        return value

    def _log_debug_request(self, mode: str, req: Dict[str, Any]) -> None:
        if not self._debug_enabled:
            return
        summary: Dict[str, Any] = {
            "id": req.get("id"),
            "method": req.get("method"),
            "mode": mode,
            "keys": sorted([k for k in req.keys() if not str(k).startswith("_")]),
        }
        params = req.get("params") or {}
        if req.get("method") == "tools/call" and isinstance(params, dict):
            args = params.get("arguments") or {}
            summary["tool"] = params.get("name")
            if isinstance(args, dict):
                summary["argument_keys"] = sorted(list(args.keys()))
                summary["arguments"] = {k: self._sanitize_value(v, k) for k, v in args.items()}
        self._log_debug(f"IN: {_json_dumps(summary)}")

    def _log_debug_response(self, mode: str, resp: Dict[str, Any]) -> None:
        if not self._debug_enabled:
            return
        summary: Dict[str, Any] = {
            "id": resp.get("id"),
            "mode": mode,
            "has_result": "result" in resp,
            "has_error": "error" in resp,
        }
        if "error" in resp and isinstance(resp["error"], dict):
            summary["error"] = self._sanitize_value(resp["error"])
        result = resp.get("result")
        if isinstance(result, dict):
            summary["result_keys"] = sorted(result.keys())
            if "content" in result:
                summary["result_content"] = "[REDACTED_CONTENT]"
        self._log_debug(f"OUT: {_json_dumps(summary)}")

def main(original_stdout: Any = None) -> None:
    # Use provided stdout or fallback to current sys.stdout
    clean_stdout = original_stdout or sys.stdout
    server = LocalSearchMCPServer(WorkspaceManager.resolve_workspace_root())
    # Ensure the worker loop uses the correct output stream
    server._original_stdout = clean_stdout
    server.run()

if __name__ == "__main__":
    main()
