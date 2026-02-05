import json
import os
import sys
import threading
import queue
import concurrent.futures
from typing import Any, Dict, Optional, List
from sari.mcp.workspace_registry import Registry
from sari.core.workspace import WorkspaceManager
from sari.core.settings import settings
from sari.mcp.policies import PolicyEngine
from sari.mcp.middleware import PolicyMiddleware, run_middlewares
from sari.mcp.tools.registry import ToolContext, build_default_registry
from sari.mcp.telemetry import TelemetryLogger

try:
    import orjson as _orjson
except Exception:
    _orjson = None

def _json_dumps(obj: Any) -> str:
    if _orjson:
        return _orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj)


class LocalSearchMCPServer:
    """
    Modernized MCP Server for Sari.
    Delegates workspace management to WorkspaceRegistry.
    """
    PROTOCOL_VERSION = "2025-11-25"
    SERVER_NAME = "sari"
    SERVER_VERSION = settings.VERSION

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.registry = Registry.get_instance()
        self.policy_engine = PolicyEngine(mode=settings.SEARCH_FIRST_MODE)
        self.logger = TelemetryLogger(WorkspaceManager.get_global_log_dir())
        self._tool_registry = build_default_registry()
        self._middlewares = [PolicyMiddleware(self.policy_engine)]
        # Add maxsize to prevent memory bloat under heavy load
        self._req_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=settings.get_int("MCP_QUEUE_SIZE", 1000))
        self._stop = threading.Event()
        self._stdout_lock = threading.Lock()
        max_workers = int(os.environ.get("SARI_MCP_WORKERS", "4") or 4)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        root_uri = params.get("rootUri") or params.get("rootPath")
        if root_uri:
            # Update workspace if provided by client
            roots = WorkspaceManager.resolve_workspace_roots(root_uri=root_uri)
            if roots: self.workspace_root = roots[0]
            
        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": {"name": self.SERVER_NAME, "version": self.SERVER_VERSION},
            "capabilities": {"tools": {}}
        }

    def handle_initialized(self, params: Dict[str, Any]) -> None:
        """Called by client after initialize response is received."""
        # Optional: Start background tasks here if needed
        pass

    def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # Lazily get or create session (Config/DB/Indexer init happens here)
        session = self.registry.get_or_create(self.workspace_root)
        
        tool_name = params.get("name")
        args = params.get("arguments", {})

        ctx = ToolContext(
            db=session.db, 
            engine=getattr(session.db, "engine", None), 
            indexer=session.indexer,
            roots=session.config_data.get("workspace_roots", [self.workspace_root]), 
            cfg=None, # Legacy config object removed
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
        method, params, msg_id = request.get("method"), request.get("params", {}), request.get("id")
        if msg_id is None: return None # Ignore notifications for now
        
        try:
            if method == "initialize": result = self.handle_initialize(params)
            elif method == "tools/list": result = {"tools": self._tool_registry.list_tools()}
            elif method == "tools/call": result = self.handle_tools_call(params)
            elif method == "ping": result = {}
            else: return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(e)}}

    def run(self) -> None:
        """Standard MCP JSON-RPC loop with Hybrid framing (Content-Length or JSONL)."""
        self._log_debug("Sari MCP Server starting run loop...")
        input_stream = sys.stdin.buffer
        try:
            while not self._stop.is_set():
                # 1. Read first line to detect framing mode
                line = input_stream.readline()
                if not line:
                    break
                
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                if line_str.startswith("{"):
                    # JSONL mode: First line is already the JSON body
                    body_str = line_str
                elif line_str.lower().startswith("content-length:"):
                    # Content-Length mode: Parse headers
                    headers = {}
                    parts = line_str.split(":", 1)
                    headers[parts[0].strip().lower()] = parts[1].strip()
                    
                    # Read remaining headers
                    while True:
                        h_line = input_stream.readline()
                        if not h_line:
                            break
                        h_str = h_line.decode("utf-8").strip()
                        if not h_str:
                            break # Header-Body separator
                        if ":" in h_str:
                            k, v = h_str.split(":", 1)
                            headers[k.strip().lower()] = v.strip()
                    
                    try:
                        content_length = int(headers.get("content-length", 0))
                    except (ValueError, TypeError):
                        continue

                    if content_length <= 0:
                        continue

                    body_bytes = input_stream.read(content_length)
                    if not body_bytes:
                        break
                    body_str = body_bytes.decode("utf-8")
                else:
                    # Unknown line, skip
                    self._log_debug(f"Unknown input line: {line_str}")
                    continue
                
                self._log_debug(f"IN: {body_str}")
                
                try:
                    req = json.loads(body_str)
                    # Async dispatch to avoid blocking the read loop
                    self._req_queue.put(req)
                except Exception as e:
                    self._log_debug(f"ERROR parsing input JSON: {e} | Body: {body_str}")
        except Exception as e:
            self._log_debug(f"CRITICAL in run loop: {e}")
        finally:
            self._log_debug("Sari MCP Server shutting down...")
            self.shutdown()

    def shutdown(self) -> None:
        """Graceful shutdown of all resources."""
        if self._stop.is_set():
            return
        self._stop.set()
        
        # 1. Stop processing new requests
        try:
            self._executor.shutdown(wait=True, cancel_futures=True)
        except Exception:
            pass
            
        # 2. Cleanup all workspace resources (DB, Engine)
        try:
            self.registry.shutdown_all()
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

    def _handle_and_respond(self, req: Dict[str, Any]) -> None:
        try:
            resp = self.handle_request(req)
            if resp:
                with self._stdout_lock:
                    # Use the explicit stdout handle provided during initialization
                    target = getattr(self, "_original_stdout", sys.stdout)
                    json_resp = _json_dumps(resp)
                    
                    # --- DEBUG LOGGING ---
                    self._log_debug(f"OUT: {json_resp}")
                    
                    # Content-Length framing for output
                    body_bytes = json_resp.encode("utf-8")
                    header = f"Content-Length: {len(body_bytes)}\r\n\r\n"
                    
                    # Try to write to buffer if available (standard for sys.stdout)
                    if hasattr(target, "buffer"):
                        target.buffer.write(header.encode("ascii"))
                        target.buffer.write(body_bytes)
                        target.buffer.flush()
                    else:
                        target.write(header)
                        target.write(json_resp)
                        target.flush()
        except Exception as e:
            self._log_debug(f"ERROR in _handle_and_respond: {e}")

    def _log_debug(self, message: str) -> None:
        """Log MCP traffic to a dedicated debug file."""
        try:
            log_path = Path.home() / ".local" / "share" / "sari" / "mcp_debug.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                import time
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass

def main(original_stdout: Any = None) -> None:
    # Use provided stdout or fallback to current sys.stdout
    clean_stdout = original_stdout or sys.stdout
    server = LocalSearchMCPServer(WorkspaceManager.resolve_workspace_root())
    # Ensure the worker loop uses the correct output stream
    server._original_stdout = clean_stdout
    server.run()

if __name__ == "__main__":
    main()
