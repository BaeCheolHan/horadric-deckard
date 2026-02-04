#!/usr/bin/env python3
"""
List files tool for Local Search MCP Server.
"""
import json
import time
from typing import Any, Dict, List

try:
    from sari.core.db import LocalSearchDB
    from sari.mcp.telemetry import TelemetryLogger
    from sari.mcp.tools._util import mcp_response, pack_header, pack_line, pack_truncated, pack_encode_id, resolve_root_ids
except ImportError:
    # Fallback for direct script execution
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from sari.core.db import LocalSearchDB
    from sari.mcp.telemetry import TelemetryLogger
    from sari.mcp.tools._util import mcp_response, pack_header, pack_line, pack_truncated, pack_encode_id, resolve_root_ids


def execute_list_files(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger, roots: List[str]) -> Dict[str, Any]:
    """Execute list_files tool."""
    start_ts = time.time()
    root_ids = resolve_root_ids(roots)

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

    summary_only = bool(args.get("summary", False)) or (not repo)
    summary_payload_budget = 2000  # bytes, target for repo-less summary output

    # --- JSON Builder (Legacy) ---
    def build_json() -> Dict[str, Any]:
        if summary_only:
            repo_stats = db.get_repo_stats(root_ids=root_ids)
            repos_all = [{"repo": k, "file_count": v} for k, v in repo_stats.items()]
            repos_all.sort(key=lambda r: r["file_count"], reverse=True)
            total = sum(repo_stats.values())
            repos: List[Dict[str, Any]] = []
            truncated = False
            # Build compact payload and keep under budget.
            for r in repos_all:
                repos.append(r)
                payload = {
                    "files": [],
                    "meta": {
                        "total": total,
                        "returned": 0,
                        "offset": 0,
                        "limit": 0,
                        "repos": repos,
                        "include_hidden": include_hidden,
                        "mode": "summary",
                        "repos_total": len(repos_all),
                        "repos_returned": len(repos),
                        "truncated": False,
                    },
                }
                # Always use compact encoding for budget check.
                payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                if payload_bytes > summary_payload_budget:
                    repos.pop()
                    truncated = True
                    break
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
                    "repos_total": len(repos_all),
                    "repos_returned": len(repos),
                    "truncated": truncated,
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
                root_ids=root_ids,
            )
            return {
                "files": files,
                "meta": meta,
            }

    # --- PACK1 Builder ---
    def build_pack() -> str:
        if summary_only:
            repo_stats = db.get_repo_stats(root_ids=root_ids)
            repos_all = [{"repo": k, "file_count": v} for k, v in repo_stats.items()]
            repos_all.sort(key=lambda r: r["file_count"], reverse=True)
            total = sum(repo_stats.values())
            lines = [
                pack_header("list_files", {"mode": "summary"}, returned=0, total=total, total_mode="exact"),
                pack_line("m", {"include_hidden": str(include_hidden).lower()}),
                pack_line("m", {"repos_total": str(len(repos_all))}),
                pack_line("m", {"repos_returned": "0"}),
            ]
            truncated = False
            returned = 0
            for r in repos_all:
                candidate = pack_line("r", {"repo": pack_encode_id(r["repo"]), "file_count": str(r["file_count"])})
                if len(("\n".join(lines + [candidate])).encode("utf-8")) > summary_payload_budget:
                    truncated = True
                    break
                lines.append(candidate)
                returned += 1
                lines[-2] = pack_line("m", {"repos_returned": str(returned)})
            if truncated:
                lines.append(pack_truncated(0, 0, "true"))
            return "\n".join(lines)

        # Hard limit for PACK1: 200
        pack_limit = min(limit_arg, 200)

        files, meta = db.list_files(
            repo=repo,
            path_pattern=path_pattern,
            file_types=file_types,
            include_hidden=include_hidden,
            limit=pack_limit,
            offset=offset,
            root_ids=root_ids,
        )

        total = meta.get("total", 0)
        returned = len(files)
        total_mode = "exact"  # list_files usually returns exact counts via DB

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
