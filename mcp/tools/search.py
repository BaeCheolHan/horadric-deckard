#!/usr/bin/env python3
"""
Search tool for Local Search MCP Server (SSOT).
"""
import time
from typing import Any, Dict, List

from mcp.tools._util import (
    mcp_response,
    pack_header,
    pack_line,
    pack_truncated,
    pack_encode_id,
    pack_encode_text,
    resolve_root_ids,
    pack_error,
    ErrorCode,
)

try:
    from app.db import LocalSearchDB, SearchOptions
    from app.engine_runtime import EngineError
    from mcp.telemetry import TelemetryLogger
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.db import LocalSearchDB, SearchOptions
    from app.engine_runtime import EngineError
    from mcp.telemetry import TelemetryLogger


def execute_search(
    args: Dict[str, Any],
    db: LocalSearchDB,
    logger: TelemetryLogger,
    roots: List[str],
    engine: Any = None,
) -> Dict[str, Any]:
    start_ts = time.time()
    engine = engine or getattr(db, "engine", None)

    root_ids = resolve_root_ids(roots)
    req_root_ids = args.get("root_ids")
    if isinstance(req_root_ids, list):
        req_root_ids = [str(r) for r in req_root_ids if r]
        if root_ids:
            root_ids = [r for r in root_ids if r in req_root_ids]
        else:
            root_ids = list(req_root_ids)
        if req_root_ids and not root_ids:
            if db and db.has_legacy_paths():
                root_ids = []
            else:
                return mcp_response(
                    "search",
                    lambda: pack_error("search", ErrorCode.ERR_ROOT_OUT_OF_SCOPE, "root_ids out of scope", hints=["outside final_roots"]),
                    lambda: {"error": {"code": ErrorCode.ERR_ROOT_OUT_OF_SCOPE.value, "message": "root_ids out of scope"}, "isError": True},
                )

    query = (args.get("query") or "").strip()
    if not query:
        return mcp_response(
            "search",
            lambda: pack_error("search", ErrorCode.INVALID_ARGS, "query is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "query is required"}, "isError": True},
        )

    repo = args.get("scope") or args.get("repo")
    if repo == "workspace":
        repo = None

    file_types = list(args.get("file_types", []))
    search_type = args.get("type")
    if search_type == "docs":
        doc_exts = ["md", "txt", "pdf", "docx", "rst", "pdf"]
        file_types.extend([e for e in doc_exts if e not in file_types])

    try:
        limit = int(args.get("limit", 8))
    except (ValueError, TypeError):
        limit = 8
    limit = max(1, min(limit, 50))

    try:
        offset = max(int(args.get("offset", 0)), 0)
    except (ValueError, TypeError):
        offset = 0

    try:
        raw_lines = int(args.get("context_lines", 5))
        snippet_lines = min(max(raw_lines, 1), 20)
    except (ValueError, TypeError):
        snippet_lines = 5

    total_mode = str(args.get("total_mode") or "").strip().lower()
    if total_mode not in {"exact", "approx"}:
        total_mode = "exact"

    engine_mode = "sqlite"
    index_version = ""
    if engine and hasattr(engine, "status"):
        st = engine.status()
        engine_mode = st.engine_mode
        index_version = st.index_version
        if engine_mode == "embedded" and not st.engine_ready:
            return mcp_response(
                "search",
                lambda: pack_error("search", ErrorCode.ERR_ENGINE_UNAVAILABLE, f"engine_ready=false reason={st.reason}", hints=[st.hint] if st.hint else None),
                lambda: {
                    "error": {"code": ErrorCode.ERR_ENGINE_UNAVAILABLE.value, "message": f"engine_ready=false reason={st.reason}", "hint": st.hint},
                    "isError": True,
                },
            )

    opts = SearchOptions(
        query=query,
        repo=repo,
        limit=limit,
        offset=offset,
        snippet_lines=snippet_lines,
        file_types=file_types,
        path_pattern=args.get("path_pattern"),
        exclude_patterns=args.get("exclude_patterns", []),
        recency_boost=bool(args.get("recency_boost", False)),
        use_regex=bool(args.get("use_regex", False)),
        case_sensitive=bool(args.get("case_sensitive", False)),
        total_mode=total_mode,
        root_ids=root_ids,
    )

    try:
        hits, meta = engine.search_v2(opts) if engine else ([], {})
    except EngineError as exc:
        code = getattr(ErrorCode, exc.code, ErrorCode.ERR_ENGINE_QUERY)
        return mcp_response(
            "search",
            lambda: pack_error("search", code, exc.message, hints=[exc.hint] if exc.hint else None),
            lambda: {"error": {"code": code.value, "message": exc.message, "hint": exc.hint}, "isError": True},
        )
    except Exception as exc:
        return mcp_response(
            "search",
            lambda: pack_error("search", ErrorCode.ERR_ENGINE_QUERY, f"engine query failed: {exc}"),
            lambda: {"error": {"code": ErrorCode.ERR_ENGINE_QUERY.value, "message": f"engine query failed: {exc}"}, "isError": True},
        )

    latency_ms = int((time.time() - start_ts) * 1000)
    total = meta.get("total", -1)
    total_mode = meta.get("total_mode", total_mode)

    def build_json() -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        for hit in hits:
            results.append({
                "doc_id": hit.path,
                "repo": hit.repo,
                "path": hit.path,
                "score": hit.score,
                "snippet": hit.snippet,
                "mtime": hit.mtime,
                "size": hit.size,
                "match_count": hit.match_count,
                "file_type": hit.file_type,
                "hit_reason": hit.hit_reason,
                "context_symbol": hit.context_symbol,
                "docstring": hit.docstring,
                "metadata": hit.metadata,
            })
        return {
            "query": query,
            "limit": limit,
            "offset": offset,
            "results": results,
            "meta": {
                "total": total,
                "total_mode": total_mode,
                "engine": engine_mode,
                "latency_ms": latency_ms,
                "index_version": index_version,
            },
        }

    def build_pack() -> str:
        returned = len(hits)
        header = pack_header("search", {"q": pack_encode_text(query)}, returned=returned)
        lines = [header]
        lines.append(pack_line("m", {"total": str(total)}))
        lines.append(pack_line("m", {"total_mode": total_mode}))
        lines.append(pack_line("m", {"engine": engine_mode}))
        lines.append(pack_line("m", {"latency_ms": str(latency_ms)}))
        if index_version:
            lines.append(pack_line("m", {"index_version": pack_encode_id(index_version)}))
        for h in hits:
            lines.append(pack_line("r", {
                "path": pack_encode_id(h.path),
                "repo": pack_encode_id(h.repo),
                "score": f"{h.score:.3f}",
                "mtime": str(h.mtime),
                "size": str(h.size),
                "file_type": pack_encode_id(h.file_type),
                "snippet": pack_encode_text(h.snippet),
            }))
        if returned >= limit:
            lines.append(pack_truncated(offset + limit, limit, "maybe"))
        return "\n".join(lines)

    return mcp_response("search", build_pack, build_json)
