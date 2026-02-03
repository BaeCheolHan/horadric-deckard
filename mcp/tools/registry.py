from dataclasses import dataclass
from typing import Any, Callable, Dict, List

import mcp.tools.search as search_tool
import mcp.tools.status as status_tool
import mcp.tools.repo_candidates as repo_candidates_tool
import mcp.tools.list_files as list_files_tool
import mcp.tools.read_file as read_file_tool
import mcp.tools.search_symbols as search_symbols_tool
import mcp.tools.read_symbol as read_symbol_tool
import mcp.tools.doctor as doctor_tool
import mcp.tools.search_api_endpoints as search_api_endpoints_tool
import mcp.tools.index_file as index_file_tool
import mcp.tools.rescan as rescan_tool
import mcp.tools.scan_once as scan_once_tool
import mcp.tools.get_callers as get_callers_tool
import mcp.tools.get_implementations as get_implementations_tool
import mcp.tools.deckard_guide as deckard_guide_tool


@dataclass
class ToolContext:
    db: Any
    engine: Any
    indexer: Any
    roots: List[str]
    cfg: Any
    logger: Any
    workspace_root: str
    server_version: str


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[ToolContext, Dict[str, Any]], Dict[str, Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in self._tools.values()
        ]

    def execute(self, name: str, ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return self._tools[name].handler(ctx, args)


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(Tool(
        name="sari_guide",
        description="Usage guide. Call this if unsure; it enforces search-first workflow.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda ctx, args: deckard_guide_tool.execute_deckard_guide(args),
    ))

    reg.register(Tool(
        name="search",
        description="SEARCH FIRST. Use before opening files to locate relevant paths/symbols.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (keywords, function names, regex)"},
                "repo": {"type": "string", "description": "Limit search to specific repository"},
                "limit": {"type": "integer", "description": "Maximum results (default: 10, max: 50)", "default": 10},
                "offset": {"type": "integer", "description": "Pagination offset (default: 0)", "default": 0},
                "file_types": {"type": "array", "items": {"type": "string"}, "description": "Filter by file extensions"},
                "path_pattern": {"type": "string", "description": "Glob pattern for path matching"},
                "exclude_patterns": {"type": "array", "items": {"type": "string"}, "description": "Patterns to exclude"},
                "recency_boost": {"type": "boolean", "description": "Boost recently modified files", "default": False},
                "use_regex": {"type": "boolean", "description": "Treat query as regex pattern", "default": False},
                "case_sensitive": {"type": "boolean", "description": "Case-sensitive search", "default": False},
                "context_lines": {"type": "integer", "description": "Number of context lines in snippet", "default": 5},
                "total_mode": {"type": "string", "enum": ["exact", "approx"], "description": "Total count mode"},
                "root_ids": {"type": "array", "items": {"type": "string"}, "description": "Limit search to specific root_ids"},
                "scope": {"type": "string", "description": "Alias for 'repo'"},
                "type": {"type": "string", "enum": ["docs", "code"], "description": "Filter by type: 'docs' or 'code'"},
            },
            "required": ["query"],
        },
        handler=lambda ctx, args: search_tool.execute_search(args, ctx.db, ctx.logger, ctx.roots, engine=ctx.engine),
    ))

    reg.register(Tool(
        name="status",
        description="Get indexer status. Use details=true for per-repo stats.",
        input_schema={"type": "object", "properties": {"details": {"type": "boolean", "default": False}}},
        handler=lambda ctx, args: status_tool.execute_status(args, ctx.indexer, ctx.db, ctx.cfg, ctx.workspace_root, ctx.server_version, ctx.logger),
    ))

    reg.register(Tool(
        name="rescan",
        description="Trigger an async rescan of the workspace index.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda ctx, args: rescan_tool.execute_rescan(args, ctx.indexer),
    ))

    reg.register(Tool(
        name="scan_once",
        description="Run a synchronous scan once (blocking).",
        input_schema={"type": "object", "properties": {}},
        handler=lambda ctx, args: scan_once_tool.execute_scan_once(args, ctx.indexer),
    ))

    reg.register(Tool(
        name="repo_candidates",
        description="Suggest top repos for a query. Use before search if repo is unknown.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 3}}, "required": ["query"]},
        handler=lambda ctx, args: repo_candidates_tool.execute_repo_candidates(args, ctx.db, ctx.logger, ctx.roots),
    ))

    reg.register(Tool(
        name="list_files",
        description="List indexed files with filters. If repo is omitted, returns repo summary only.",
        input_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "path_pattern": {"type": "string"},
                "file_types": {"type": "array", "items": {"type": "string"}},
                "include_hidden": {"type": "boolean", "default": False},
                "summary": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 100},
                "offset": {"type": "integer", "default": 0},
            },
        },
        handler=lambda ctx, args: list_files_tool.execute_list_files(args, ctx.db, ctx.logger, ctx.roots),
    ))

    reg.register(Tool(
        name="read_file",
        description="Read full file content by path. Use only after search narrows candidates.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=lambda ctx, args: read_file_tool.execute_read_file(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="search_symbols",
        description="Search for symbols by name. Prefer this to scanning files.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 20}}, "required": ["query"]},
        handler=lambda ctx, args: search_symbols_tool.execute_search_symbols(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="read_symbol",
        description="Read symbol definition block by name/path. Use after search_symbols.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}, "name": {"type": "string"}}, "required": ["path", "name"]},
        handler=lambda ctx, args: read_symbol_tool.execute_read_symbol(args, ctx.db, ctx.logger, ctx.roots),
    ))

    reg.register(Tool(
        name="doctor",
        description="Run health checks and return structured diagnostics.",
        input_schema={
            "type": "object",
            "properties": {
                "include_network": {"type": "boolean", "default": True},
                "include_port": {"type": "boolean", "default": True},
                "include_db": {"type": "boolean", "default": True},
                "include_disk": {"type": "boolean", "default": True},
                "include_daemon": {"type": "boolean", "default": True},
                "include_venv": {"type": "boolean", "default": True},
                "include_marker": {"type": "boolean", "default": False},
                "port": {"type": "integer", "default": 47800},
                "min_disk_gb": {"type": "number", "default": 1.0},
            },
        },
        handler=lambda ctx, args: doctor_tool.execute_doctor(args),
    ))

    reg.register(Tool(
        name="search_api_endpoints",
        description="Search API endpoints by path pattern (search-first for APIs).",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=lambda ctx, args: search_api_endpoints_tool.execute_search_api_endpoints(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="index_file",
        description="Force immediate re-indexing for a file path. Use when content seems stale.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=lambda ctx, args: index_file_tool.execute_index_file(args, ctx.indexer, ctx.roots),
    ))

    reg.register(Tool(
        name="get_callers",
        description="Find callers of a symbol (use after search_symbols).",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        handler=lambda ctx, args: get_callers_tool.execute_get_callers(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="get_implementations",
        description="Find implementations of a symbol (use after search_symbols).",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        handler=lambda ctx, args: get_implementations_tool.execute_get_implementations(args, ctx.db, ctx.roots),
    ))

    return reg
