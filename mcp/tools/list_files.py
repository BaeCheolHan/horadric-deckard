#!/usr/bin/env python3
"""
List files tool for Local Search MCP Server.
"""
import json
import time
import os
from typing import Any, Dict

try:
    from app.db import LocalSearchDB
    from mcp.telemetry import TelemetryLogger
except ImportError:
    # Fallback for direct script execution
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.db import LocalSearchDB
    from mcp.telemetry import TelemetryLogger


def execute_list_files(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger) -> Dict[str, Any]:
    """Execute list_files tool."""
    start_ts = time.time()
    repo = args.get("repo")
    path_pattern = args.get("path_pattern")
    file_types = args.get("file_types")
    include_hidden = bool(args.get("include_hidden", False))
    compact = str(os.environ.get("DECKARD_RESPONSE_COMPACT") or "1").strip().lower() not in {"0", "false", "no", "off"}

    paths = []
    if compact:
        files, _ = db.list_files(
            repo=repo,
            path_pattern=path_pattern,
            file_types=file_types,
            include_hidden=include_hidden,
            limit=int(args.get("limit", 100)),
            offset=int(args.get("offset", 0)),
        )
        paths = [f["path"] for f in files]
        output = {"paths": paths}
        json_output = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    else:
        summary_only = bool(args.get("summary", False)) or (not repo and not path_pattern and not file_types)
        if summary_only:
            files: list[dict[str, Any]] = []
            repo_stats = db.get_repo_stats()
            repos = [{"repo": k, "file_count": v} for k, v in repo_stats.items()]
            repos.sort(key=lambda r: r["file_count"], reverse=True)
            total = sum(repo_stats.values())
            output = {
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
                limit=int(args.get("limit", 100)),
                offset=int(args.get("offset", 0)),
            )
            output = {
                "files": files,
                "meta": meta,
            }
        json_output = json.dumps(output, ensure_ascii=False, indent=2)
    
    # Telemetry: Log list_files stats
    latency_ms = int((time.time() - start_ts) * 1000)
    payload_bytes = len(json_output.encode('utf-8'))
    repo_val = repo or ("summary" if (not compact and not repo and not path_pattern and not file_types) else "all")
    file_count = len(paths) if compact else len(output.get("files", []))
    logger.log_telemetry(f"tool=list_files repo='{repo_val}' files={file_count} payload_bytes={payload_bytes} latency={latency_ms}ms")
    
    return {
        "content": [{"type": "text", "text": json_output}],
    }
