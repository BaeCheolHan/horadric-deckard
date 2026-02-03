#!/usr/bin/env python3
"""
Search tool for Local Search MCP Server.
"""
import time
from typing import Any, Dict, List

from mcp.tools._util import mcp_response, pack_header, pack_line, pack_truncated, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode

try:
    from app.db import LocalSearchDB, SearchOptions
    from mcp.telemetry import TelemetryLogger
except ImportError:
    # Fallback for direct script execution
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.db import LocalSearchDB, SearchOptions
    from mcp.telemetry import TelemetryLogger


def execute_search(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger, roots: List[str]) -> Dict[str, Any]:
    """Execute enhanced search tool (v2.5.0) with PACK1 support."""
    start_ts = time.time()
    root_ids = resolve_root_ids(roots)
    query = args.get("query", "")
    
    if not query.strip():
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
    
    # v2.5.4: Robust integer parsing & Strict Policy Enforcement
    try:
        raw_limit = int(args.get("limit", 8))
        # Default limit logic differs slightly per format, but base input processing is here.
        # PACK1 will clamp to 20 later. JSON keeps existing logic.
        limit_arg = min(raw_limit, 20)
    except (ValueError, TypeError):
        limit_arg = 8
        
    try:
        offset = max(int(args.get("offset", 0)), 0)
    except (ValueError, TypeError):
        offset = 0

    try:
        # Policy: Max 20 lines
        raw_lines = int(args.get("context_lines", 5))
        snippet_lines = min(raw_lines, 20)
    except (ValueError, TypeError):
        snippet_lines = 5

    # Determine total_mode based on scale (v2.5.1)
    # This logic is common for both formats
    total_mode_hint = "exact"
    if db:
        status = db.get_index_status()
        total_files = status.get("total_files", 0)
        repo_stats = db.get_repo_stats(root_ids=root_ids)
        total_repos = len(repo_stats)
        
        if total_repos > 50 or total_files > 150000:
            total_mode_hint = "approx"
        elif total_repos > 20 or total_files > 50000:
            if args.get("path_pattern"):
                total_mode_hint = "approx"

    # --- Common Search Execution ---
    # We define a helper to run search with specific limit
    last_meta: Dict[str, Any] = {}

    def run_search(final_limit: int):
        nonlocal last_meta
        opts = SearchOptions(
            query=query,
            repo=repo,
            limit=final_limit,
            offset=offset,
            snippet_lines=snippet_lines,
            file_types=file_types,
            path_pattern=args.get("path_pattern"),
            exclude_patterns=args.get("exclude_patterns", []),
            recency_boost=bool(args.get("recency_boost", False)),
            use_regex=bool(args.get("use_regex", False)),
            case_sensitive=bool(args.get("case_sensitive", False)),
            total_mode=total_mode_hint,
            root_ids=root_ids,
        )
        hits, meta = db.search_v2(opts)
        last_meta = meta or {}
        return hits, meta

    # --- JSON Builder (Legacy) ---
    def build_json() -> Dict[str, Any]:
        # Legacy JSON limit logic
        hits, db_meta = run_search(limit_arg)
        
        results: List[Dict[str, Any]] = []
        for hit in hits:
            repo_display = hit.repo if hit.repo != "__root__" else "(root)"
            result = {
                "repo": hit.repo,
                "repo_display": repo_display,
                "path": hit.path,
                "score": hit.score,
                "reason": hit.hit_reason,
                "snippet": hit.snippet,
            }
            # Add optional fields
            for attr in ["mtime", "size", "match_count", "file_type", "context_symbol"]:
                val = getattr(hit, attr, None)
                if val: result[attr] = val
            
            if hasattr(hit, 'docstring') and hit.docstring:
                doc_lines = hit.docstring.splitlines()
                summary = "\n".join(doc_lines[:3])
                if len(doc_lines) > 3: summary += "\n..."
                result["docstring"] = summary
            results.append(result)

        # Result Grouping & Meta (Reuse existing logic structure)
        repo_groups = {}
        for r in results:
            rp = r["repo"]
            if rp not in repo_groups: repo_groups[rp] = {"count": 0, "top_score": 0.0}
            repo_groups[rp]["count"] += 1
            repo_groups[rp]["top_score"] = max(repo_groups[rp]["top_score"], r["score"])
        top_repos = sorted(repo_groups.keys(), key=lambda k: repo_groups[k]["top_score"], reverse=True)[:2]
        
        scope = f"repo:{repo}" if repo else "workspace"
        
        total_from_db = db_meta.get("total", 0)
        total_mode = db_meta.get("total_mode", "exact")
        
        if total_mode == "approx" and total_from_db == -1:
            if len(results) >= limit_arg:
                total = offset + limit_arg + 1
                has_more = True
            else:
                total = offset + len(results)
                has_more = False
        else:
            total = total_from_db
            has_more = total > (offset + limit_arg)

        is_exact_total = (total_mode == "exact")
        filtered_total = None
        if args.get("exclude_patterns") and total > 0:
             is_exact_total = False
             filtered_total = offset + len(results)
        
        warnings = []
        if has_more:
            next_offset = offset + limit_arg
            warnings.append(f"More results available. Use offset={next_offset} to see next page.")
        if total_mode == "approx": warnings.append("Total count is approximate.")
        if not repo and total > 50: warnings.append("Many results found. Consider specifying 'repo'.")

        fallback_reason_code = None
        if db_meta.get("fallback_used"): fallback_reason_code = "FTS_FAILED"
        elif not results and total == 0: fallback_reason_code = "NO_MATCHES"

        output = {
            "query": query,
            "scope": scope,
            "total": total,
            "total_mode": total_mode,
            "is_exact_total": is_exact_total,
            "approx_total": total if total_mode == "approx" else None,
            "filtered_total": filtered_total,
            "limit": limit_arg,
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + limit_arg if has_more else None,
            "warnings": warnings,
            "results": results,
            "repo_summary": repo_groups,
            "top_candidate_repos": top_repos,
            "meta": {
                "total_mode": total_mode,
                "fallback_used": db_meta.get("fallback_used", False),
                "fallback_reason_code": fallback_reason_code,
                "total_scanned": db_meta.get("total_scanned", 0),
                "regex_mode": db_meta.get("regex_mode", False),
                "regex_error": db_meta.get("regex_error"),
            },
        }
        
        if not results:
            # Hints logic
            reason = "No matches found."
            output["meta"]["fallback_reason"] = reason
            output["hints"] = ["Try a broader query or remove filters."] # Simplified for brevity here

        return output

    # --- PACK1 Builder ---
    def build_pack() -> str:
        # Hard limit for PACK1: 20
        pack_limit = min(limit_arg, 20)
        hits, db_meta = run_search(pack_limit)
        
        returned = len(hits)
        total = db_meta.get("total", 0)
        total_mode = db_meta.get("total_mode", "exact")
        
        # Header
        kv = {"q": pack_encode_text(query)}
        if repo:
            kv["repo"] = pack_encode_id(repo)
            
        lines = [
            pack_header("search", kv, returned=returned, total=total, total_mode=total_mode)
        ]
        
        # Records
        for hit in hits:
            # Snippet processing
            # 1. Normalize line endings
            raw_snip = hit.snippet or ""
            norm_snip = raw_snip.replace("\r\n", "\n").replace("\r", "\n")
            # 2. Hard limit 120 chars (raw)
            trim_snip = norm_snip[:120]
            # 3. Encode
            enc_snip = pack_encode_text(trim_snip)
            
            # Extract line number from snippet (e.g. "L10: ...")
            # If parsing fails, default to 0
            line_num = "0"
            import re
            m = re.search(r"L(\d+):", raw_snip)
            if m:
                line_num = m.group(1)
            
            # r:repo=<repo> path=<path> line=<line> col=<col?> s=<snippet>
            kv_line = {
                "repo": pack_encode_id(hit.repo),
                "path": pack_encode_id(hit.path),
                "line": line_num,
                "s": enc_snip
            }
            # Column is optional/not always available in Hit object directly depending on DB impl
            # Assuming hit.column doesn't exist or is not critical for now based on Plan "col=<col?>"
            
            lines.append(pack_line("r", kv_line))
            
        # Truncation
        # Calculate next offset logic similar to JSON
        has_more = False
        if total_mode == "approx" and total == -1:
             has_more = (returned >= pack_limit)
        else:
             has_more = total > (offset + returned)
             
        truncated_state = "true" if (total_mode == "exact" and has_more) else ("maybe" if has_more else "false")
        
        if has_more:
            next_off = offset + returned
            lines.append(pack_truncated(next_off, pack_limit, truncated_state))
            
        return "\n".join(lines)

    # Execute
    response = mcp_response("search", build_pack, build_json)
    
    # Telemetry logging (Simplified)
    latency_ms = int((time.time() - start_ts) * 1000)
    fallback_used = last_meta.get("fallback_used", False)
    total_mode = last_meta.get("total_mode", "exact")
    logger.log_telemetry(
        f"tool=search query='{query}' latency={latency_ms}ms fallback_used={fallback_used} total_mode={total_mode}"
    )
    
    return response
