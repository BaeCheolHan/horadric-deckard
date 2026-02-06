#!/usr/bin/env python3
"""
Scan-once tool for Local Search MCP Server.
"""
from typing import Any, Dict
import time
from sari.mcp.tools._util import mcp_response, pack_header, pack_line, pack_error, ErrorCode
from sari.core.indexer import Indexer


def execute_scan_once(args: Dict[str, Any], indexer: Indexer, logger: Any) -> Dict[str, Any]:
    """Run a synchronous scan once."""
    if not indexer:
        return mcp_response(
            "scan_once",
            lambda: pack_error("scan_once", ErrorCode.INTERNAL, "indexer not available"),
            lambda: {"error": {"code": ErrorCode.INTERNAL.value, "message": "indexer not available"}, "isError": True},
        )

    if not getattr(indexer, "indexing_enabled", True):
        mode = getattr(indexer, "indexer_mode", "off")
        code = ErrorCode.ERR_INDEXER_DISABLED if mode == "off" else ErrorCode.ERR_INDEXER_FOLLOWER
        return mcp_response(
            "scan_once",
            lambda: pack_error("scan_once", code, "Indexer is not available in follower/off mode", fields={"mode": mode}),
            lambda: {"error": {"code": code.value, "message": "Indexer is not available in follower/off mode", "data": {"mode": mode}}, "isError": True},
        )

    indexer.scan_once()
    # Best-effort drain so synchronous callers observe committed results.
    deadline = time.time() + 8.0
    stable_rounds = 0
    while time.time() < deadline:
        depths = indexer.get_queue_depths() if hasattr(indexer, "get_queue_depths") else {}
        fair_q = int(depths.get("fair_queue", 0))
        priority_q = int(depths.get("priority_queue", 0))
        db_q = int(depths.get("db_writer", 0))
        if fair_q == 0 and priority_q == 0 and db_q == 0:
            stable_rounds += 1
            if stable_rounds >= 3:
                break
        else:
            stable_rounds = 0
        time.sleep(0.1)
    try:
        if hasattr(indexer, "storage") and hasattr(indexer.storage, "writer"):
            indexer.storage.writer.flush(timeout=2.0)
    except Exception:
        pass
    try:
        scanned = indexer.status.scanned_files
        indexed = indexer.status.indexed_files
    except Exception:
        scanned = 0
        indexed = 0

    def build_json() -> Dict[str, Any]:
        return {"ok": True, "scanned_files": scanned, "indexed_files": indexed}

    def build_pack() -> str:
        lines = [pack_header("scan_once", {}, returned=1)]
        lines.append(pack_line("m", kv={"ok": "true"}))
        lines.append(pack_line("m", kv={"scanned_files": str(scanned)}))
        lines.append(pack_line("m", kv={"indexed_files": str(indexed)}))
        return "\n".join(lines)

    return mcp_response("scan_once", build_pack, build_json)
