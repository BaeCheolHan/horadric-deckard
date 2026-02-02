#!/usr/bin/env python3
"""
MCP Server for Local Search (STDIO mode)
Follows Model Context Protocol specification: https://modelcontextprotocol.io/specification/2025-11-25

v2.5.0 enhancements:
- Search pagination (offset, total, has_more)
- Detailed status stats (repo_stats)
- Improved UX (root display, fallback reasons)

Usage:
  python3 .codex/tools/deckard/mcp/server.py

Environment:
  LOCAL_SEARCH_WORKSPACE_ROOT - Workspace root directory (default: cwd)
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

from app.config import Config
from app.db import LocalSearchDB, SearchOptions
from app.indexer import Indexer
from app.workspace import WorkspaceManager
from mcp.telemetry import TelemetryLogger

# Import tools using absolute paths
import mcp.tools.search as search_tool
import mcp.tools.status as status_tool
import mcp.tools.repo_candidates as repo_candidates_tool
import mcp.tools.list_files as list_files_tool
import mcp.tools.read_file as read_file_tool
import mcp.tools.search_symbols as search_symbols_tool
import mcp.tools.read_symbol as read_symbol_tool


class LocalSearchMCPServer:
    """MCP Server for Local Search - STDIO mode."""
    
    PROTOCOL_VERSION = "2025-11-25"
    SERVER_NAME = "deckard"
    # Version is injected via environment variable by the bootstrapper
    @staticmethod
    def _resolve_version() -> str:
        v = (os.environ.get("DECKARD_VERSION") or "").strip()
        if v:
            return v
        ver_path = REPO_ROOT / "VERSION"
        if ver_path.exists():
            try:
                return ver_path.read_text(encoding="utf-8").strip() or "dev"
            except Exception:
                pass
        return "dev"

    SERVER_VERSION = _resolve_version.__func__()
    
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.cfg: Optional[Config] = None
        self.db: Optional[LocalSearchDB] = None
        self.indexer: Optional[Indexer] = None
        self._indexer_thread: Optional[threading.Thread] = None
        self._initialized = False
        self._init_lock = threading.Lock()
        
        # Initialize telemetry logger
        self.logger = TelemetryLogger(WorkspaceManager.get_global_log_dir())
    
    def _ensure_initialized(self) -> None:
        """Lazy initialization of database and indexer."""
        if self._initialized:
            return
        
        with self._init_lock:
            # Double-check after acquiring lock
            if self._initialized:
                return

            try:
                config_path = Path(self.workspace_root) / ".codex" / "tools" / "deckard" / "config" / "config.json"
                if config_path.exists():
                    self.cfg = Config.load(str(config_path), workspace_root_override=self.workspace_root)
                else:
                    self.cfg = Config(
                        workspace_root=self.workspace_root,
                        server_host="127.0.0.1",
                        server_port=47777,
                        scan_interval_seconds=180,
                        snippet_max_lines=5,
                        max_file_bytes=800000,
                        db_path=str(WorkspaceManager.get_local_db_path(self.workspace_root)),
                        include_ext=[".py", ".js", ".ts", ".java", ".kt", ".go", ".rs", ".md", ".json", ".yaml", ".yml", ".sh"],
                        include_files=["pom.xml", "package.json", "Dockerfile", "Makefile", "build.gradle", "settings.gradle"],
                        exclude_dirs=[".git", "node_modules", "__pycache__", ".venv", "venv", "target", "build", "dist", "coverage", "vendor"],
                        exclude_globs=["*.min.js", "*.min.css", "*.map", "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
                        redact_enabled=True,
                        commit_batch_size=500,
                    )
                
                db_path = Path(self.cfg.db_path)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                self.db = LocalSearchDB(str(db_path))
                self.logger.log_info(f"DB path: {db_path}")
                
                self.indexer = Indexer(self.cfg, self.db, self.logger)
                
                self._indexer_thread = threading.Thread(target=self.indexer.run_forever, daemon=True)
                self._indexer_thread.start()
                
                init_timeout = float(os.environ.get("DECKARD_INIT_TIMEOUT") or os.environ.get("LOCAL_SEARCH_INIT_TIMEOUT") or "5")
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
        new_workspace = WorkspaceManager.resolve_workspace_root(params.get("rootUri") or params.get("rootPath"))
        
        # Thread-safe workspace change
        with self._init_lock:
            if new_workspace != self.workspace_root:
                self.workspace_root = new_workspace
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
        """Handle tools/list request - v2.5.0 enhanced schema."""
        return {
            "tools": [
                {
                    "name": "search",
                    "description": "Enhanced search for code/files with pagination. Use BEFORE file exploration to save tokens.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (keywords, function names, regex)",
                            },
                            "repo": {
                                "type": "string",
                                "description": "Limit search to specific repository",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default: 10, max: 50)",
                                "default": 10,
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Pagination offset (default: 0)",
                                "default": 0,
                            },
                            "file_types": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Filter by file extensions, e.g., ['py', 'ts']",
                            },
                            "path_pattern": {
                                "type": "string",
                                "description": "Glob pattern for path matching, e.g., 'src/**/*.ts'",
                            },
                            "exclude_patterns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Patterns to exclude, e.g., ['node_modules']",
                            },
                            "recency_boost": {
                                "type": "boolean",
                                "description": "Boost recently modified files (default: false)",
                                "default": False,
                            },
                            "use_regex": {
                                "type": "boolean",
                                "description": "Treat query as regex pattern (default: false)",
                                "default": False,
                            },
                            "case_sensitive": {
                                "type": "boolean",
                                "description": "Case-sensitive search (default: false)",
                                "default": False,
                            },
                            "context_lines": {
                                "type": "integer",
                                "description": "Number of context lines in snippet (default: 5)",
                                "default": 5,
                             },
                            "scope": {
                                "type": "string",
                                "description": "Alias for 'repo'",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["docs", "code"],
                                "description": "Filter by type: 'docs' or 'code'",
                            },
                         },
                        "required": ["query"],
                    },
                },
                {
                    "name": "status",
                    "description": "Get indexer status. Use details=true for per-repo stats.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "details": {
                                "type": "boolean",
                                "description": "Include detailed repo stats (default: false)",
                                "default": False,
                            }
                        },
                    },
                },
                {
                    "name": "repo_candidates",
                    "description": "Find candidate repositories for a query.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Query to find relevant repositories",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum candidates (default: 3)",
                                "default": 3,
                            },
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "list_files",
                    "description": "List indexed files for debugging.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "repo": {
                                "type": "string",
                                "description": "Filter by repository name",
                            },
                            "path_pattern": {
                                "type": "string",
                                "description": "Glob pattern for path matching",
                            },
                            "file_types": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Filter by file extensions",
                            },
                            "include_hidden": {
                                "type": "boolean",
                                "description": "Include hidden directories (default: false)",
                                "default": False,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default: 100)",
                                "default": 100,
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Pagination offset (default: 0)",
                                "default": 0,
                            },
                        },
                    },
                },
                {
                    "name": "read_file",
                    "description": "Read file content from the index.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path or relative path (if unique) to the file",
                            }
                        },
                        "required": ["path"],
                    },
                },
                {
                    "name": "search_symbols",
                    "description": "Search for code symbols (classes, functions, etc.).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Symbol name to search for (supports fuzzy matching)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default: 20)",
                                "default": 20,
                            },
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "read_symbol",
                    "description": "Read specific symbol definition (function/class) to save tokens.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path containing the symbol",
                            },
                            "name": {
                                "type": "string",
                                "description": "Name of the symbol (function/class name)",
                            },
                        },
                        "required": ["path", "name"],
                    },
                },
            ],
        }
    
    def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_initialized()
        
        tool_name = params.get("name")
        args = params.get("arguments", {})
        
        if tool_name == "search":
            return self._tool_search(args)
        elif tool_name == "status":
            return self._tool_status(args)
        elif tool_name == "repo_candidates":
            return self._tool_repo_candidates(args)
        elif tool_name == "list_files":
            return self._tool_list_files(args)
        elif tool_name == "read_file":
            return self._tool_read_file(args)
        elif tool_name == "search_symbols":
            return self._tool_search_symbols(args)
        elif tool_name == "read_symbol":
            return self._tool_read_symbol(args)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    def _tool_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute enhanced search tool (v2.5.0)."""
        return search_tool.execute_search(args, self.db, self.logger)
    
    def _tool_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return status_tool.execute_status(args, self.indexer, self.db, self.cfg, self.workspace_root, self.SERVER_VERSION)
    
    def _tool_repo_candidates(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return repo_candidates_tool.execute_repo_candidates(args, self.db)
    
    def _tool_list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return list_files_tool.execute_list_files(args, self.db, self.logger)

    def _tool_read_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return read_file_tool.execute_read_file(args, self.db)

    def _tool_search_symbols(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return search_symbols_tool.execute_search_symbols(args, self.db)
        
    def _tool_read_symbol(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return read_symbol_tool.execute_read_symbol(args, self.db, self.logger)
    
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
        def _read_mcp_message(stdin):
            line = stdin.readline()
            if not line:
                return None, None
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
            payload = json.dumps(resp).encode("utf-8")
            if mode == "jsonl":
                sys.stdout.buffer.write(payload + b"\n")
                sys.stdout.buffer.flush()
            else:
                header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                sys.stdout.buffer.write(header + payload)
                sys.stdout.buffer.flush()

        try:
            stdin = sys.stdin.buffer
            while True:
                body, mode = _read_mcp_message(stdin)
                if body is None:
                    break
                try:
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
