#!/usr/bin/env python3
"""
Rescan tool for Local Search MCP Server.
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


def execute_rescan(args: Dict[str, Any], indexer: Indexer) -> Dict[str, Any]:
    """Trigger async rescan on indexer."""
    if not indexer:
        return {
            "content": [{"type": "text", "text": "Error: indexer not available"}],
            "isError": True,
        }

    indexer.request_rescan()

    def build_json() -> Dict[str, Any]:
        return {"requested": True}

    def build_pack() -> str:
        lines = [pack_header("rescan", {}, returned=1)]
        lines.append(pack_line("m", kv={"requested": "true"}))
        return "\n".join(lines)

    return mcp_response("rescan", build_pack, build_json)
