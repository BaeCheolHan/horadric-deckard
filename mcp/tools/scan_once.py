#!/usr/bin/env python3
"""
Scan-once tool for Local Search MCP Server.
"""
from typing import Any, Dict

from mcp.tools._util import mcp_response, pack_header, pack_line

try:
    from app.indexer import Indexer
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.indexer import Indexer


def execute_scan_once(args: Dict[str, Any], indexer: Indexer) -> Dict[str, Any]:
    """Run a synchronous scan once."""
    if not indexer:
        return {
            "content": [{"type": "text", "text": "Error: indexer not available"}],
            "isError": True,
        }

    indexer.scan_once()
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
