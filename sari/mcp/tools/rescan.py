#!/usr/bin/env python3
"""
Rescan tool for Local Search MCP Server.
"""
from typing import Any, Dict
from sari.mcp.tools._util import mcp_response, pack_header, pack_line, pack_error, ErrorCode
from sari.core.indexer import Indexer


def execute_rescan(args: Dict[str, Any], indexer: Indexer) -> Dict[str, Any]:
    """Trigger async rescan on indexer."""
    if not indexer:
        return mcp_response(
            "rescan",
            lambda: pack_error("rescan", ErrorCode.INTERNAL, "indexer not available"),
            lambda: {"error": {"code": ErrorCode.INTERNAL.value, "message": "indexer not available"}, "isError": True},
        )

    if not getattr(indexer, "indexing_enabled", True):
        mode = getattr(indexer, "indexer_mode", "off")
        code = ErrorCode.ERR_INDEXER_DISABLED if mode == "off" else ErrorCode.ERR_INDEXER_FOLLOWER
        return mcp_response(
            "rescan",
            lambda: pack_error("rescan", code, "Indexer is not available in follower/off mode", fields={"mode": mode}),
            lambda: {"error": {"code": code.value, "message": "Indexer is not available in follower/off mode", "data": {"mode": mode}}, "isError": True},
        )

    # Prefer async queue trigger when available.
    if hasattr(indexer, "request_rescan"):
        indexer.request_rescan()
    # Compatibility fallback for older/newer indexer variants.
    elif hasattr(indexer, "scan_once"):
        indexer.scan_once()
    else:
        return mcp_response(
            "rescan",
            lambda: pack_error("rescan", ErrorCode.INTERNAL, "indexer does not support rescan"),
            lambda: {"error": {"code": ErrorCode.INTERNAL.value, "message": "indexer does not support rescan"}, "isError": True},
        )

    def build_json() -> Dict[str, Any]:
        return {"requested": True}

    def build_pack() -> str:
        lines = [pack_header("rescan", {}, returned=1)]
        lines.append(pack_line("m", kv={"requested": "true"}))
        return "\n".join(lines)

    return mcp_response("rescan", build_pack, build_json)
