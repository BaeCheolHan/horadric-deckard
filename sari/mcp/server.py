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
        """Standard MCP JSON-RPC loop."""
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                    # Async dispatch to avoid blocking the read loop
                    self._req_queue.put(req)
                except:
                    pass
        finally:
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
                    print(_json_dumps(resp), file=target, flush=True)
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
