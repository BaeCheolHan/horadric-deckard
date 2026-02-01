#!/usr/bin/env python3
"""
Search tool for Local Search MCP Server.
"""
import json
import time
from typing import Any, Dict, List
from db import LocalSearchDB, SearchOptions
from telemetry import TelemetryLogger


def execute_search(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger) -> Dict[str, Any]:
    """Execute enhanced search tool (v2.5.0)."""
    start_ts = time.time()
    query = args.get("query", "")
    
    if not query.strip():
        return {
            "content": [{"type": "text", "text": "Error: query is required"}],
            "isError": True,
        }
    
    repo = args.get("scope") or args.get("repo")
    if repo == "workspace":
        repo = None
    
    file_types = list(args.get("file_types", []))
    search_type = args.get("type")
    if search_type == "docs":
        doc_exts = ["md", "txt", "pdf", "docx", "rst", "pdf"]
        file_types.extend([e for e in doc_exts if e not in file_types])
    
    limit = min(int(args.get("limit", 10)), 50)
    offset = max(int(args.get("offset", 0)), 0)

    # Determine total_mode based on scale (v2.5.1)
    total_mode = "exact"
    if db:
        status = db.get_index_status()
        total_files = status.get("total_files", 0)
        repo_stats = db.get_repo_stats()
        total_repos = len(repo_stats)
        
        if total_repos > 50 or total_files > 150000:
            total_mode = "approx"
        elif total_repos > 20 or total_files > 50000:
            if args.get("path_pattern"):
                total_mode = "approx"

    opts = SearchOptions(
        query=query,
        repo=repo,
        limit=limit,
        offset=offset,
        snippet_lines=int(args.get("context_lines", 5)),
        file_types=file_types,
        path_pattern=args.get("path_pattern"),
        exclude_patterns=args.get("exclude_patterns", []),
        recency_boost=bool(args.get("recency_boost", False)),
        use_regex=bool(args.get("use_regex", False)),
        case_sensitive=bool(args.get("case_sensitive", False)),
        total_mode=total_mode,
    )
    
    hits, db_meta = db.search_v2(opts)
    
    results: List[Dict[str, Any]] = []
    for hit in hits:
        # UX: Remap __root__ to (root)
        repo_display = hit.repo if hit.repo != "__root__" else "(root)"
        
        result = {
            "repo": hit.repo,
            "repo_display": repo_display,
            "path": hit.path,
            "score": hit.score,
            "reason": hit.hit_reason,
            "snippet": hit.snippet,
        }
        if hit.mtime > 0:
            result["mtime"] = hit.mtime
        if hit.size > 0:
            result["size"] = hit.size
        if hit.match_count > 0:
            result["match_count"] = hit.match_count
        if hit.file_type:
            result["file_type"] = hit.file_type
        results.append(result)
    
    # Result Grouping
    repo_groups = {}
    for r in results:
        repo = r["repo"]
        if repo not in repo_groups:
            repo_groups[repo] = {"count": 0, "top_score": 0.0}
        repo_groups[repo]["count"] += 1
        repo_groups[repo]["top_score"] = max(repo_groups[repo]["top_score"], r["score"])
    
    # Sort repos by top_score
    top_repos = sorted(repo_groups.keys(), key=lambda k: repo_groups[k]["top_score"], reverse=True)[:2]
    
    scope = f"repo:{opts.repo}" if opts.repo else "workspace"
    
    # Total/HasMore Logic (v2.5.1 Accuracy)
    total = db_meta.get("total", len(results))
    total_mode = db_meta.get("total_mode", "exact")
    
    # Even if SQL total is exact, exclude_patterns might reduce it further
    is_exact_total = (total_mode == "exact")
    if opts.exclude_patterns and total > 0:
         is_exact_total = False
    
    has_more = total > (offset + limit)
    
    warnings = []
    if has_more:
        next_offset = offset + limit
        warnings.append(f"More results available. Use offset={next_offset} to see next page.")
    if not opts.repo and total > 50:
        warnings.append("Many results found. Consider specifying 'repo' to filter.")
    
    # Determine fallback reason code
    fallback_reason_code = None
    if db_meta.get("fallback_used"):
        fallback_reason_code = "FTS_FAILED" # General fallback
    elif not results and total == 0:
        fallback_reason_code = "NO_MATCHES"

    regex_error = db_meta.get("regex_error")
    if regex_error:
         warnings.append(f"Regex Error: {regex_error}")

    output = {
        "query": query,
        "scope": scope,
        "total": total,
        "total_mode": total_mode,
        "is_exact_total": is_exact_total,
        "approx_total": total if total_mode == "approx" else None,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
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
            "regex_error": regex_error,
        },
    }
    
    if not results:
        reason = "No matches found."
        active_filters = []
        if opts.repo: active_filters.append(f"repo='{opts.repo}'")
        if opts.file_types: active_filters.append(f"file_types={opts.file_types}")
        if opts.path_pattern: active_filters.append(f"path_pattern='{opts.path_pattern}'")
        if opts.exclude_patterns: active_filters.append(f"exclude_patterns={opts.exclude_patterns}")
        
        if active_filters:
            reason = f"No matches found with filters: {', '.join(active_filters)}"
        
        output["meta"]["fallback_reason"] = reason
        
        hints = [
            "Try a broader query or remove filters.",
            "Check if the file is indexed using 'list_files' tool.",
            "If searching for a specific pattern, try 'use_regex=true'."
        ]
        if opts.file_types or opts.path_pattern:
            hints.insert(0, "Try removing 'file_types' or 'path_pattern' filters.")
        
        output["hints"] = hints
    
    
    # Telemetry: Log search stats
    latency_ms = int((time.time() - start_ts) * 1000)
    snippet_chars = sum(len(r.get("snippet", "")) for r in results)
    
    logger.log_telemetry(f"tool=search query='{opts.query}' results={len(results)} snippet_chars={snippet_chars} latency={latency_ms}ms")

    return {
        "content": [{"type": "text", "text": json.dumps(output, indent=2, ensure_ascii=False)}],
    }
