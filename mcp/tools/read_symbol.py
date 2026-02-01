#!/usr/bin/env python3
"""
Read Symbol Tool for Local Search MCP Server.
Reads only the specific code block (function/class) of a symbol.
"""
import json
import time
from typing import Any, Dict

try:
    from app.db import LocalSearchDB
    from mcp.telemetry import TelemetryLogger
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.db import LocalSearchDB
    from mcp.telemetry import TelemetryLogger


def execute_read_symbol(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger) -> Dict[str, Any]:
    """Execute read_symbol tool (v2.7.0)."""
    start_ts = time.time()
    
    path = args.get("path")
    symbol_name = args.get("name")
    
    if not path or not symbol_name:
        return {
            "content": [{"type": "text", "text": "Error: 'path' and 'name' are required."}],
            "isError": True,
        }
        
    block = db.get_symbol_block(path, symbol_name)
    
    latency_ms = int((time.time() - start_ts) * 1000)
    logger.log_telemetry(f"tool=read_symbol path='{path}' name='{symbol_name}' found={bool(block)} latency={latency_ms}ms")

    if not block:
        return {
            "content": [{"type": "text", "text": f"Error: Symbol '{symbol_name}' not found in '{path}' (or no block range available)."}],
            "isError": True,
        }
    
    # Format output
    output = (
        f"File: {path}\n"
        f"Symbol: {block['name']}\n"
        f"Range: L{block['start_line']} - L{block['end_line']}\n"
        f"--------------------------------------------------\n"
        f"{block['content']}\n"
        f"--------------------------------------------------"
    )

    return {
        "content": [{"type": "text", "text": output}],
    }
