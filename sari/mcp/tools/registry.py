import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import sari.mcp.tools.search as search_tool
import sari.mcp.tools.status as status_tool
import sari.mcp.tools.repo_candidates as repo_candidates_tool
import sari.mcp.tools.list_files as list_files_tool
import sari.mcp.tools.read_file as read_file_tool
import sari.mcp.tools.grep_and_read as grep_and_read_tool
import sari.mcp.tools.search_symbols as search_symbols_tool
import sari.mcp.tools.read_symbol as read_symbol_tool
import sari.mcp.tools.doctor as doctor_tool
import sari.mcp.tools.search_api_endpoints as search_api_endpoints_tool
import sari.mcp.tools.index_file as index_file_tool
import sari.mcp.tools.rescan as rescan_tool
import sari.mcp.tools.scan_once as scan_once_tool
import sari.mcp.tools.get_callers as get_callers_tool
import sari.mcp.tools.get_implementations as get_implementations_tool
import sari.mcp.tools.guide as guide_tool
import sari.mcp.tools.call_graph as call_graph_tool
import sari.mcp.tools.call_graph_health as call_graph_health_tool
import sari.mcp.tools.save_snippet as save_snippet_tool
import sari.mcp.tools.get_snippet as get_snippet_tool
import sari.mcp.tools.archive_context as archive_context_tool
import sari.mcp.tools.get_context as get_context_tool
import sari.mcp.tools.dry_run_diff as dry_run_diff_tool


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[["ToolContext", Dict[str, Any]], Dict[str, Any]]
    hidden: bool = False


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
    policy_engine: Optional[Any] = None  # Added for policy tracking


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        expose_internal = os.environ.get("SARI_EXPOSE_INTERNAL_TOOLS", "").strip().lower() in {"1", "true", "yes", "on"}
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self._tools.values()
            if (not t.hidden) or expose_internal
        ]

    def execute(self, name: str, ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
            
        result = tool.handler(ctx, args)
        
        # Post-execution policy hook: Mark search actions automatically
        if ctx.policy_engine and not result.get("isError"):
            if name in {"search", "search_symbols", "grep_and_read"}:
                ctx.policy_engine.mark_action(name)
                
        return result


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(Tool(
        name="sari_guide",
        description="Usage guide. Call this if unsure; it enforces search-first workflow.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda ctx, args: guide_tool.execute_sari_guide(args),
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
        name="grep_and_read",
        description="Composite tool: search then read top files.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "repo": {"type": "string", "description": "Limit search to specific repository"},
                "limit": {"type": "integer", "description": "Maximum search results (default: 8)", "default": 8},
                "read_limit": {"type": "integer", "description": "Files to read from top results (default: 3)", "default": 3},
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
            },
            "required": ["query"],
        },
        handler=lambda ctx, args: grep_and_read_tool.execute_grep_and_read(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="status",
        description="Get indexer status. Use details=true for per-repo stats.",
        input_schema={"type": "object", "properties": {"details": {"type": "boolean", "default": False}}},
        handler=lambda ctx, args: status_tool.execute_status(args, ctx.indexer, ctx.db, ctx.cfg, ctx.workspace_root, ctx.server_version, ctx.logger),
    ))

    reg.register(Tool(
        name="rescan",
        description="(Internal) Trigger an async rescan of the workspace index.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda ctx, args: rescan_tool.execute_rescan(args, ctx.indexer),
        hidden=True,
    ))

    reg.register(Tool(
        name="scan_once",
        description="(Internal) Run a synchronous scan once (blocking).",
        input_schema={"type": "object", "properties": {}},
        handler=lambda ctx, args: scan_once_tool.execute_scan_once(args, ctx.indexer, ctx.logger),
        hidden=True,
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
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "repo": {"type": "string"},
                "kinds": {"type": "array", "items": {"type": "string"}},
                "path_prefix": {"type": "string"},
                "match_mode": {"type": "string", "enum": ["contains", "prefix", "exact"], "default": "contains"},
                "include_qualname": {"type": "boolean", "default": True},
                "case_sensitive": {"type": "boolean", "default": False},
                "root_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
        handler=lambda ctx, args: search_symbols_tool.execute_search_symbols(args, ctx.db, ctx.logger, ctx.roots),
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

    reg.register(Tool(
        name="call_graph",
        description="Call graph for a symbol (upstream/downstream).",
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "symbol_id": {"type": "string"},
                "path": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
                "include_path": {"type": "array", "items": {"type": "string"}},
                "exclude_path": {"type": "array", "items": {"type": "string"}},
                "sort": {"type": "string", "enum": ["line", "name"], "default": "line"},
                "quality_score": {"type": "number"},
            },
            "required": ["symbol"],
        },
        handler=lambda ctx, args: call_graph_tool.execute_call_graph(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="call_graph_health",
        description="Check call-graph plugin health and API compatibility.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda ctx, args: call_graph_health_tool.execute_call_graph_health(args),
    ))

    reg.register(Tool(
        name="save_snippet",
        description="Save code snippet with a tag.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "tag": {"type": "string"},
                "note": {"type": "string"},
                "commit": {"type": "string"},
            },
            "required": ["path", "tag"],
        },
        handler=lambda ctx, args: save_snippet_tool.execute_save_snippet(args, ctx.db, ctx.roots, indexer=ctx.indexer),
    ))

    reg.register(Tool(
        name="get_snippet",
        description="Retrieve saved snippets by tag or query.",
        input_schema={
            "type": "object",
            "properties": {
                "tag": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=lambda ctx, args: get_snippet_tool.execute_get_snippet(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="archive_context",
        description="Archive domain knowledge/context.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "related_files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topic", "content"],
        },
        handler=lambda ctx, args: archive_context_tool.execute_archive_context(args, ctx.db, ctx.roots, indexer=ctx.indexer),
    ))

    reg.register(Tool(
        name="get_context",
        description="Retrieve archived context by topic or query.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=lambda ctx, args: get_context_tool.execute_get_context(args, ctx.db, ctx.roots),
    ))

    reg.register(Tool(
        name="dry_run_diff",
        description="Preview diff and run lightweight syntax check before editing.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=lambda ctx, args: dry_run_diff_tool.execute_dry_run_diff(args, ctx.db, ctx.roots),
    ))

    return reg
