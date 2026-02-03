#!/usr/bin/env python3
"""
List files tool for Local Search MCP Server.
"""
import time
from typing import Any, Dict

try:
    from app.db import LocalSearchDB
    from mcp.telemetry import TelemetryLogger
    from mcp.tools._util import mcp_response, pack_header, pack_line, pack_truncated, pack_encode_id
except ImportError:
    # Fallback for direct script execution
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.db import LocalSearchDB
    from mcp.telemetry import TelemetryLogger
    from mcp.tools._util import mcp_response, pack_header, pack_line, pack_truncated, pack_encode_id


def execute_list_files(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger) -> Dict[str, Any]:
    """Execute list_files tool."""
    start_ts = time.time()
    
    # Parse args
    repo = args.get("repo")
    path_pattern = args.get("path_pattern")
    file_types = args.get("file_types")
    include_hidden = bool(args.get("include_hidden", False))
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
        
    try:
        limit_arg = int(args.get("limit", 100))
    except (ValueError, TypeError):
        limit_arg = 100

    # --- JSON Builder (Legacy) ---
    def build_json() -> Dict[str, Any]:
        summary_only = bool(args.get("summary", False)) or (not repo and not path_pattern and not file_types)
        
        if summary_only:
            repo_stats = db.get_repo_stats()
            repos = [{"repo": k, "file_count": v} for k, v in repo_stats.items()]
            repos.sort(key=lambda r: r["file_count"], reverse=True)
            total = sum(repo_stats.values())
            return {
                "files": [],
                "meta": {
                    "total": total,
                    "returned": 0,
                    "offset": 0,
                    "limit": 0,
                    "repos": repos,
                    "include_hidden": include_hidden,
                    "mode": "summary",
                },
            }
        else:
            files, meta = db.list_files(
                repo=repo,
                path_pattern=path_pattern,
                file_types=file_types,
                include_hidden=include_hidden,
                limit=limit_arg,
                offset=offset,
            )
            return {
                "files": files,
                "meta": meta,
            }

    # --- PACK1 Builder ---
    def build_pack() -> str:
        # Hard limit for PACK1: 200
        pack_limit = min(limit_arg, 200)
        
        files, meta = db.list_files(
            repo=repo,
            path_pattern=path_pattern,
            file_types=file_types,
            include_hidden=include_hidden,
            limit=pack_limit,
            offset=offset,
        )
        
        total = meta.get("total", 0)
        returned = len(files)
        total_mode = "exact" # list_files usually returns exact counts via DB
        
        # Header
        kv = {
            "offset": offset,
            "limit": pack_limit
        }
        lines = [
            pack_header("list_files", kv, returned=returned, total=total, total_mode=total_mode)
        ]
        
        # Records
        for f in files:
            # p:<path> (ENC_ID)
            path_enc = pack_encode_id(f["path"])
            lines.append(pack_line("p", single_value=path_enc))
            
        # Truncation
        is_truncated = (offset + returned) < total
        if is_truncated:
            next_offset = offset + returned
            lines.append(pack_truncated(next_offset, pack_limit, "true"))
            
        return "\n".join(lines)

    # Execute and Telemetry
    response = mcp_response("list_files", build_pack, build_json)
    
    # Telemetry logging
    latency_ms = int((time.time() - start_ts) * 1000)
    # Estimate payload size (rough)
    payload_text = response["content"][0]["text"]
    payload_bytes = len(payload_text.encode('utf-8'))
    
    # Log simplified telemetry
    repo_val = repo or "all"
    item_count = payload_text.count('\n') if "PACK1" in payload_text else 0 # Approximation for PACK
    if "PACK1" not in payload_text:
         # Rough count for JSON without parsing
         item_count = payload_text.count('"path":')
         
    logger.log_telemetry(f"tool=list_files repo='{repo_val}' items={item_count} payload_bytes={payload_bytes} latency={latency_ms}ms")
    
    return response
