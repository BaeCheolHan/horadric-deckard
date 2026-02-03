#!/usr/bin/env python3
"""
Repo candidates tool for Deckard MCP Server.
"""
import json
from typing import Any, Dict
from mcp.tools._util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text

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


def execute_repo_candidates(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger = None) -> Dict[str, Any]:
    """Execute repo_candidates tool."""
    query = args.get("query", "")
    try:
        limit_arg = min(int(args.get("limit", 3)), 5)
    except (ValueError, TypeError):
        limit_arg = 3
    
    if not query.strip():
        return {
            "content": [{"type": "text", "text": "Error: query is required"}],
            "isError": True,
        }
    
    def get_candidates():
        candidates = db.repo_candidates(q=query, limit=limit_arg)
        for candidate in candidates:
            score = candidate.get("score", 0)
            if score >= 10:
                reason = f"High match ({score} files contain '{query}')"
            elif score >= 5:
                reason = f"Moderate match ({score} files)"
            else:
                reason = f"Low match ({score} files)"
            candidate["reason"] = reason
        return candidates

    # --- JSON Builder ---
    def build_json() -> Dict[str, Any]:
        candidates = get_candidates()
        return {
            "query": query,
            "candidates": candidates,
            "hint": "Use 'repo' parameter in search to narrow down scope after selection",
        }

    # --- PACK1 Builder ---
    def build_pack() -> str:
        candidates = get_candidates()
        
        # Header
        kv = {"q": pack_encode_text(query), "limit": limit_arg}
        lines = [
            pack_header("repo_candidates", kv, returned=len(candidates))
        ]
        
        # Records
        for c in candidates:
            # r:repo=<repo> score=<score> reason=<reason>
            kv_line = {
                "repo": pack_encode_id(c["repo"]),
                "score": str(c["score"]),
                "reason": pack_encode_text(c["reason"])
            }
            lines.append(pack_line("r", kv_line))
            
        return "\n".join(lines)

    if logger:
        # We need candidate count for logging, but don't want to run query twice optimally.
        # But for simplicity in this structure, we let builders run query. 
        # Telemetry here might be slightly off if we don't capture result from mcp_response, 
        # but execute_repo_candidates returns the result, so we can't easily hook in unless we move logging inside builders or after mcp_response.
        # Let's log *after* mcp_response call by peeking result, or just log query intent.
        logger.log_telemetry(f"tool=repo_candidates query='{query}' limit={limit_arg}")

    return mcp_response("repo_candidates", build_pack, build_json)
