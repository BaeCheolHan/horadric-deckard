#!/usr/bin/env python3
"""
List files tool for Local Search MCP Server.
"""
import json
import time
from typing import Any, Dict
from db import LocalSearchDB
from telemetry import TelemetryLogger


def execute_list_files(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger) -> Dict[str, Any]:
    """Execute list_files tool."""
    start_ts = time.time()
    files, meta = db.list_files(
        repo=args.get("repo"),
        path_pattern=args.get("path_pattern"),
        file_types=args.get("file_types"),
        include_hidden=bool(args.get("include_hidden", False)),
        limit=int(args.get("limit", 100)),
        offset=int(args.get("offset", 0)),
    )
    
    output = {
        "files": files,
        "meta": meta,
    }
    
    json_output = json.dumps(output, indent=2, ensure_ascii=False)
    
    # Telemetry: Log list_files stats
    latency_ms = int((time.time() - start_ts) * 1000)
    payload_bytes = len(json_output.encode('utf-8'))
    repo_val = args.get("repo", "all")
    logger.log_telemetry(f"tool=list_files repo='{repo_val}' files={len(files)} payload_bytes={payload_bytes} latency={latency_ms}ms")
    
    return {
        "content": [{"type": "text", "text": json_output}],
    }
