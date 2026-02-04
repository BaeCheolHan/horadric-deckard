#!/usr/bin/env python3
"""
MCP Server for Local Search (STDIO mode)
Follows Model Context Protocol specification: https://modelcontextprotocol.io/specification/2025-11-25

Enhancements:
- Search pagination (offset, total, has_more)
- Detailed status stats (repo_stats)
- Improved UX (root display, fallback reasons)

Usage:
  python3 .codex/tools/sari/mcp/server.py

Environment:
  SARI_WORKSPACE_ROOT - Workspace root directory (default: cwd)
"""
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to sys.path for absolute imports
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sari.core.config import Config
from sari.core.db import LocalSearchDB, SearchOptions
from sari.core.indexer import Indexer
from sari.core.workspace import WorkspaceManager
from sari.mcp.telemetry import TelemetryLogger

# Import tools using absolute paths
import sari.mcp.tools.search as search_tool
import sari.mcp.tools.status as status_tool
import sari.mcp.tools.repo_candidates as repo_candidates_tool
import sari.mcp.tools.list_files as list_files_tool
import sari.mcp.tools.read_file as read_file_tool
import sari.mcp.tools.search_symbols as search_symbols_tool
import sari.mcp.tools.read_symbol as read_symbol_tool
import sari.mcp.tools.doctor as doctor_tool
import sari.mcp.tools.search_api_endpoints as search_api_endpoints_tool
import sari.mcp.tools.index_file as index_file_tool
import sari.mcp.tools.rescan as rescan_tool
import sari.mcp.tools.scan_once as scan_once_tool
import sari.mcp.tools.get_callers as get_callers_tool
import sari.mcp.tools.get_implementations as get_implementations_tool
import sari.mcp.tools.guide as sari_guide_tool
from sari.mcp.tools.registry import ToolContext, build_default_registry


class LocalSearchMCPServer:
    """MCP Server for Local Search - STDIO mode."""

    PROTOCOL_VERSION = "2025-11-25"
    SERVER_NAME = "sari"
    # Resolve version from package metadata first; env is fallback for overrides.
    @staticmethod
    def _resolve_version() -> str:
        # 1. Try to import from version.py
        try:
            from sari.version import __version__
            return __version__
        except ImportError:
            pass
        # 2. Environment Variable (override in bootstrap/test)
        v = (os.environ.get("SARI_VERSION") or "").strip()
        if v:
            return v
        return "dev"

    SERVER_VERSION = _resolve_version.__func__()

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self._root_uri: Optional[str] = None
        self.cfg: Optional[Config] = None
        self.db: Optional[LocalSearchDB] = None
        self.indexer: Optional[Indexer] = None
        self._indexer_thread: Optional[threading.Thread] = None
        self._initialized = False
        self._init_lock = threading.Lock()
        self._search_first_mode = self._resolve_search_first_policy()
        self._search_usage = {
            "search": 0,
            "search_symbols": 0,
            "last_search_ts": None,
            "last_search_symbols_ts": None,
            "read_without_search": 0,
        }
        self._tool_registry = build_default_registry()

        # Initialize telemetry logger
        self.logger = TelemetryLogger(WorkspaceManager.get_global_log_dir())

    @staticmethod
    def _resolve_search_first_policy() -> str:
        # Check SARI_
        from sari.core.config import _get_env_any
        raw_mode = (_get_env_any("SEARCH_FIRST_MODE") or "").strip().lower()
        if raw_mode in {"off", "warn", "enforce"}:
            return raw_mode
        raw_enforce = (_get_env_any("ENFORCE_SEARCH_FIRST") or "").strip().lower()
        if raw_enforce:
            return "off" if raw_enforce in {"0", "false", "no", "off"} else "enforce"
        return "warn"

    def _mark_search(self, kind: str) -> None:
        now = time.time()
        if kind == "search":
            self._search_usage["search"] += 1
            self._search_usage["last_search_ts"] = now
        elif kind == "search_symbols":
            self._search_usage["search_symbols"] += 1
            self._search_usage["last_search_symbols_ts"] = now

    def _has_search_context(self) -> bool:
        return (self._search_usage.get("search", 0) > 0 or
                self._search_usage.get("search_symbols", 0) > 0)

    def _search_first_error(self) -> Dict[str, Any]:
        self._search_usage["read_without_search"] += 1
        try:
            self.logger.log_telemetry(
                f"policy=search_first mode={self._search_first_mode} action=enforce violations={self._search_usage['read_without_search']}"
            )
        except Exception:
            pass
        from sari.mcp.tools._util import mcp_response, pack_error, ErrorCode
        return mcp_response(
            "search_first",
            lambda: pack_error("search_first", ErrorCode.INVALID_ARGS, "search-first policy active. Call search/search_symbols before read_file/read_symbol."),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "search-first policy active. Call search/search_symbols before read_file/read_symbol."}, "isError": True},
        )

    def _search_first_warning(self, result: Dict[str, Any]) -> Dict[str, Any]:
        self._search_usage["read_without_search"] += 1
        try:
            self.logger.log_telemetry(
                f"policy=search_first mode={self._search_first_mode} action=warn violations={self._search_usage['read_without_search']}"
            )
        except Exception:
            pass
        warnings = list(result.get("warnings", []))
        warnings.append("Search-first policy (advisory): call search/search_symbols before read_file/read_symbol.")
        result["warnings"] = warnings
        return result

    def _ensure_initialized(self) -> None:
        """Lazy initialization of database and indexer."""
        if self._initialized:
            return

        with self._init_lock:
            # Double-check after acquiring lock
            if self._initialized:
                return

            try:
                config_path = WorkspaceManager.resolve_config_path(self.workspace_root)
                self.cfg = Config.load(str(config_path), workspace_root_override=self.workspace_root, root_uri=self._root_uri)

                db_path = Path(self.cfg.db_path)

                db_path.parent.mkdir(parents=True, exist_ok=True)
                self.db = LocalSearchDB(str(db_path))
                try:
                    from sari.core.engine_registry import get_default_engine
                    self.db.set_engine(get_default_engine(self.db, self.cfg, self.cfg.workspace_roots))
                except Exception as e:
                    self.logger.log_error(f"engine init failed: {e}")
                self.logger.log_info(f"DB path: {db_path}")

                from sari.core.indexer import resolve_indexer_settings
                mode, enabled, startup_enabled, lock_handle = resolve_indexer_settings(str(db_path))
                self.indexer = Indexer(self.cfg, self.db, self.logger, indexer_mode=mode, indexing_enabled=enabled, startup_index_enabled=startup_enabled, lock_handle=lock_handle)

                self._indexer_thread = threading.Thread(target=self.indexer.run_forever, daemon=True)
                self._indexer_thread.start()

                init_timeout = float(os.environ.get("SARI_INIT_TIMEOUT") or "5")
                if init_timeout > 0:
                    wait_iterations = int(init_timeout * 10)
                    for _ in range(wait_iterations):
                        if self.indexer.status.index_ready:
                            break
                        time.sleep(0.1)

                self._initialized = True
            except Exception as e:
                self.logger.log_error(f"Initialization failed: {e}")
                raise


    def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # Trace full initialize payload to verify what clients send.
        try:
            self.logger.log_info(
                "Initialize params (full): "
                + json.dumps(params, ensure_ascii=False)
            )
        except Exception as e:
            self.logger.log_error(f"Initialize params log failed: {e}")

        # Parse rootUri from client or detect fallback
        root_uri = params.get("rootUri") or params.get("rootPath")
        roots = WorkspaceManager.resolve_workspace_roots(root_uri=root_uri)
        new_workspace = roots[0] if roots else WorkspaceManager.resolve_workspace_root()

        # Thread-safe workspace change
        with self._init_lock:
            if new_workspace != self.workspace_root:
                self.workspace_root = new_workspace
                self._root_uri = root_uri
                self._initialized = False  # Force re-initialization with new workspace
                self.logger.log_info(f"Workspace set to: {self.workspace_root}")

        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": {
                "name": self.SERVER_NAME,
                "version": self.SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
            },
        }

    def handle_initialized(self, params: Dict[str, Any]) -> None:
        self._ensure_initialized()

    def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request -  enhanced schema."""
        return {"tools": self._tool_registry.list_tools()}

    def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_initialized()

        tool_name = params.get("name")
        args = params.get("arguments", {})
        ctx = ToolContext(
            db=self.db,
            engine=self.db.engine if self.db else None,
            indexer=self.indexer,
            roots=self.cfg.workspace_roots if self.cfg else [],
            cfg=self.cfg,
            logger=self.logger,
            workspace_root=self.workspace_root,
            server_version=self.SERVER_VERSION,
        )

        if tool_name == "search":
            return self._tool_search(args)
        if tool_name == "read_file":
            return self._tool_read_file(args)
        if tool_name == "search_symbols":
            return self._tool_search_symbols(args)
        if tool_name == "read_symbol":
            return self._tool_read_symbol(args)
        if tool_name == "doctor":
            return self._tool_doctor(args)

        return self._tool_registry.execute(tool_name, ctx, args)

    def _tool_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute enhanced search tool ."""
        result = search_tool.execute_search(args, self.db, self.logger, self.cfg.workspace_roots, engine=self.db.engine)
        if not result.get("isError"):
            self._mark_search("search")
        return result

    def _tool_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return status_tool.execute_status(args, self.indexer, self.db, self.cfg, self.workspace_root, self.SERVER_VERSION)

    def _tool_repo_candidates(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return repo_candidates_tool.execute_repo_candidates(args, self.db, self.logger, self.cfg.workspace_roots)

    def _tool_list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return list_files_tool.execute_list_files(args, self.db, self.logger, self.cfg.workspace_roots)

    def _tool_read_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._search_first_mode != "off" and not self._has_search_context():
            if self._search_first_mode == "enforce":
                return self._search_first_error()
            result = read_file_tool.execute_read_file(args, self.db, self.cfg.workspace_roots)
            return self._search_first_warning(result)
        return read_file_tool.execute_read_file(args, self.db, self.cfg.workspace_roots)

    def _tool_search_symbols(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = search_symbols_tool.execute_search_symbols(args, self.db, self.cfg.workspace_roots)
        if not result.get("isError"):
            self._mark_search("search_symbols")
        return result

    def _tool_read_symbol(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._search_first_mode != "off" and not self._has_search_context():
            if self._search_first_mode == "enforce":
                return self._search_first_error()
            result = read_symbol_tool.execute_read_symbol(args, self.db, self.logger, self.cfg.workspace_roots)
            return self._search_first_warning(result)
        return read_symbol_tool.execute_read_symbol(args, self.db, self.logger, self.cfg.workspace_roots)

    def _tool_doctor(self, args: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(args)
        payload["search_usage"] = dict(self._search_usage)
        payload["search_first_mode"] = self._search_first_mode
        return doctor_tool.execute_doctor(payload)

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = request.get("method")
        params = request.get("params", {})
        msg_id = request.get("id")

        is_notification = msg_id is None

        try:
            if method == "initialize":
                result = self.handle_initialize(params)
            elif method == "initialized":
                self.handle_initialized(params)
                return None
            elif method == "tools/list":
                result = self.handle_tools_list(params)
            elif method == "tools/call":
                result = self.handle_tools_call(params)
            elif method == "ping":
                result = {}
            else:
                if is_notification:
                    return None
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

            if is_notification:
                return None

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result,
            }
        except Exception as e:
            self.logger.log_error(f"Error handling {method}: {e}")
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32000,
                    "message": str(e),
                },
            }

    def shutdown(self) -> None:
        """Stops the indexer and closes the database."""
        self.logger.log_info(f"Shutting down server for workspace: {self.workspace_root}")
        if self.indexer:
            self.indexer.stop()
        if self.db:
            self.db.close()

    def run(self) -> None:
        self.logger.log_info(f"Starting MCP server (workspace: {self.workspace_root})")
        use_text_io = not hasattr(sys.stdin, "buffer") or not hasattr(sys.stdout, "buffer")

        def _read_mcp_message(stdin):
            line = stdin.readline()
            if not line:
                return None, None
            if use_text_io:
                while line in ("\n", "\r\n"):
                    line = stdin.readline()
                    if not line:
                        return None, None

                if line.lstrip().startswith(("{", "[")):
                    return line.rstrip("\r\n"), "jsonl"

                headers = [line]
                while True:
                    h = stdin.readline()
                    if not h:
                        return None, None
                    if h in ("\n", "\r\n"):
                        break
                    headers.append(h)

                content_length = None
                for h in headers:
                    parts = h.split(":", 1)
                    if len(parts) != 2:
                        continue
                    key = parts[0].strip().lower()
                    if key == "content-length":
                        try:
                            content_length = int(parts[1].strip())
                        except ValueError:
                            pass
                        break

                if content_length is None or content_length <= 0:
                    return None, None

                body = stdin.read(content_length)
                if not body:
                    return None, None
                return body, "framed"

            while line in (b"\n", b"\r\n"):
                line = stdin.readline()
                if not line:
                    return None, None

            if line.lstrip().startswith((b"{", b"[")):
                return line.rstrip(b"\r\n"), "jsonl"

            headers = [line]
            while True:
                h = stdin.readline()
                if not h:
                    return None, None
                if h in (b"\n", b"\r\n"):
                    break
                headers.append(h)

            content_length = None
            for h in headers:
                parts = h.decode("utf-8", errors="ignore").split(":", 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip().lower()
                if key == "content-length":
                    try:
                        content_length = int(parts[1].strip())
                    except ValueError:
                        pass
                    break

            if content_length is None or content_length <= 0:
                return None, None

            body = stdin.read(content_length)
            if not body:
                return None, None
            return body, "framed"

        def _write_response(resp, mode):
            if resp is None:
                return
            if use_text_io:
                payload = json.dumps(resp)
                if mode == "jsonl":
                    sys.stdout.write(payload + "\n")
                    sys.stdout.flush()
                else:
                    header = f"Content-Length: {len(payload)}\r\n\r\n"
                    sys.stdout.write(header + payload)
                    sys.stdout.flush()
            else:
                payload = json.dumps(resp).encode("utf-8")
                if mode == "jsonl":
                    sys.stdout.buffer.write(payload + b"\n")
                    sys.stdout.buffer.flush()
                else:
                    header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                    sys.stdout.buffer.write(header + payload)
                    sys.stdout.buffer.flush()

        try:
            stdin = sys.stdin if use_text_io else sys.stdin.buffer
            while True:
                body, mode = _read_mcp_message(stdin)
                if body is None:
                    break
                try:
                    if use_text_io:
                        request = json.loads(body)
                    else:
                        request = json.loads(body.decode("utf-8"))
                    response = self.handle_request(request)
                    _write_response(response, mode)
                except json.JSONDecodeError as e:
                    self.logger.log_error(f"JSON decode error: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": "Parse error",
                        },
                    }
                    _write_response(error_response, mode)
        except KeyboardInterrupt:
            self.logger.log_info("Shutting down...")
        finally:
            if self.indexer:
                self.indexer.stop()
            if self.db:
                self.db.close()


def main() -> None:
    # Use WorkspaceManager for workspace detection
    workspace_root = WorkspaceManager.resolve_workspace_root()

    server = LocalSearchMCPServer(workspace_root)
    server.run()


if __name__ == "__main__":
    main()
