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
from typing import Any, Dict, List, Optional
from datetime import datetime

# Add parent directories to path for imports
SCRIPT_DIR = Path(__file__).parent
APP_DIR = SCRIPT_DIR.parent / "app"
sys.path.insert(0, str(APP_DIR))

from config import Config
from db import LocalSearchDB, SearchOptions
from indexer import Indexer

# Import new modules
from workspace import WorkspaceManager
from telemetry import TelemetryLogger
import tools.search
import tools.status
import tools.repo_candidates
import tools.list_files


class LocalSearchMCPServer:
    """MCP Server for Local Search - STDIO mode."""
    
    PROTOCOL_VERSION = "2025-11-25"
    SERVER_NAME = "deckard"
    SERVER_VERSION = "1.0.1"  # DB Isolation & Pagination
    
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.cfg: Optional[Config] = None
        self.db: Optional[LocalSearchDB] = None
        self.indexer: Optional[Indexer] = None
        self._indexer_thread: Optional[threading.Thread] = None
        self._initialized = False
        
        # Initialize telemetry logger
        self.logger = TelemetryLogger(WorkspaceManager.get_global_log_dir())
    
    def _ensure_initialized(self) -> None:
        """Lazy initialization of database and indexer."""
        if self._initialized:
            return
        
        try:
            os.environ["LOCAL_SEARCH_WORKSPACE_ROOT"] = self.workspace_root
            
            config_path = Path(self.workspace_root) / ".codex" / "tools" / "deckard" / "config" / "config.json"
            if config_path.exists():
                self.cfg = Config.load(str(config_path))
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
            
            debug_db_path = os.environ.get("LOCAL_SEARCH_DB_PATH", "").strip()
            if debug_db_path:
                self.logger.log_info(f"Using debug DB path override: {debug_db_path}")
                db_path = Path(os.path.expanduser(debug_db_path))
            else:
                db_path = WorkspaceManager.get_local_db_path(self.workspace_root)
            
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = LocalSearchDB(str(db_path))
            self.logger.log_info(f"DB path: {db_path}")
            
            self.indexer = Indexer(self.cfg, self.db, self.logger)
            
            self._indexer_thread = threading.Thread(target=self.indexer.run_forever, daemon=True)
            self._indexer_thread.start()
            
            init_timeout = float(os.environ.get("LOCAL_SEARCH_INIT_TIMEOUT", "5"))
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
        # Parse rootUri from client (LSP/MCP standard)
        root_uri = params.get("rootUri") or params.get("rootPath")
        if root_uri:
            if root_uri.startswith("file://"):
                new_workspace = root_uri[7:]  # Remove file:// prefix
            else:
                new_workspace = root_uri
            
            # If workspace changed, reset initialization
            if new_workspace != self.workspace_root:
                self.workspace_root = new_workspace
                self._initialized = False  # Force re-initialization with new workspace
                self.logger.log_info(f"Workspace set from rootUri: {self.workspace_root}")
        
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
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    def _tool_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute enhanced search tool (v2.5.0)."""
        return tools.search.execute_search(args, self.db, self.logger)
    
    def _tool_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return tools.status.execute_status(args, self.indexer, self.db, self.cfg, self.workspace_root, self.SERVER_VERSION)
    
    def _tool_repo_candidates(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return tools.repo_candidates.execute_repo_candidates(args, self.db)
    
    def _tool_list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return tools.list_files.execute_list_files(args, self.db, self.logger)
    
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
    
    def run(self) -> None:
        self.logger.log_info(f"Starting MCP server (workspace: {self.workspace_root})")
        
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    request = json.loads(line)
                    response = self.handle_request(request)
                    
                    if response is not None:
                        print(json.dumps(response), flush=True)
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
                    print(json.dumps(error_response), flush=True)
        except KeyboardInterrupt:
            self.logger.log_info("Shutting down...")
        finally:
            if self.indexer:
                self.indexer.stop()
            if self.db:
                self.db.close()


def main() -> None:
    # Use WorkspaceManager for workspace detection
    workspace_root = WorkspaceManager.detect_workspace()
    
    server = LocalSearchMCPServer(workspace_root)
    server.run()


if __name__ == "__main__":
    main()