#!/usr/bin/env python3
"""
Repo candidates tool for Local Search MCP Server.
"""
import json
from typing import Any, Dict
from db import LocalSearchDB
from telemetry import TelemetryLogger


def execute_repo_candidates(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger = None) -> Dict[str, Any]:
    """Execute repo_candidates tool."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 3)), 5)
    
    if not query.strip():
        return {
            "content": [{"type": "text", "text": "Error: query is required"}],
            "isError": True,
        }
    
    candidates = db.repo_candidates(q=query, limit=limit)
    
    for candidate in candidates:
        score = candidate.get("score", 0)
        if score >= 10:
            reason = f"High match ({score} files contain '{query}')"
        elif score >= 5:
            reason = f"Moderate match ({score} files)"
        else:
            reason = f"Low match ({score} files)"
        candidate["reason"] = reason
    
    output = {
        "query": query,
        "candidates": candidates,
        "hint": "Use 'repo' parameter in search to narrow down scope after selection",
    }
    
    if logger:
        logger.log_telemetry(f"tool=repo_candidates query='{query}' results={len(candidates)}")

    return {
        "content": [{"type": "text", "text": json.dumps(output, indent=2, ensure_ascii=False)}],
    }
