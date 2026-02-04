#!/usr/bin/env python3
"""
Read Symbol Tool for Local Search MCP Server.
Reads only the specific code block (function/class) of a symbol.
"""
import json
import time
from typing import Any, Dict, List

try:
    from sari.core.db import LocalSearchDB
    from sari.mcp.telemetry import TelemetryLogger
    from sari.mcp.tools._util import mcp_response, pack_error, ErrorCode, resolve_db_path, pack_header, pack_line, pack_encode_text
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from sari.core.db import LocalSearchDB
    from sari.mcp.telemetry import TelemetryLogger
    from sari.mcp.tools._util import mcp_response, pack_error, ErrorCode, resolve_db_path, pack_header, pack_line, pack_encode_text


def execute_read_symbol(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger, roots: List[str]) -> Dict[str, Any]:
    """Execute read_symbol tool."""
    start_ts = time.time()

    path = args.get("path")
    symbol_name = args.get("name")

    if not path or not symbol_name:
        return mcp_response(
            "read_symbol",
            lambda: pack_error("read_symbol", ErrorCode.INVALID_ARGS, "'path' and 'name' are required."),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "'path' and 'name' are required."}, "isError": True},
        )

    db_path = resolve_db_path(path, roots)
    if not db_path and db.has_legacy_paths():
        db_path = path
    if not db_path:
        return mcp_response(
            "read_symbol",
            lambda: pack_error("read_symbol", ErrorCode.ERR_ROOT_OUT_OF_SCOPE, f"Path out of scope: {path}", hints=["outside final_roots"]),
            lambda: {"error": {"code": ErrorCode.ERR_ROOT_OUT_OF_SCOPE.value, "message": f"Path out of scope: {path}"}, "isError": True},
        )

    block = db.get_symbol_block(db_path, symbol_name)

    latency_ms = int((time.time() - start_ts) * 1000)
    logger.log_telemetry(f"tool=read_symbol path='{path}' name='{symbol_name}' found={bool(block)} latency={latency_ms}ms")

    if not block:
        return mcp_response(
            "read_symbol",
            lambda: pack_error("read_symbol", ErrorCode.NOT_INDEXED, f"Symbol '{symbol_name}' not found in '{db_path}' (or no block range available)."),
            lambda: {"error": {"code": ErrorCode.NOT_INDEXED.value, "message": f"Symbol '{symbol_name}' not found in '{db_path}' (or no block range available)."}, "isError": True},
        )

    # Format output
    doc = block.get('docstring', '')
    meta = block.get('metadata', '{}')

    header = [
        f"File: {db_path}",
        f"Symbol: {block['name']}",
        f"Range: L{block['start_line']} - L{block['end_line']}"
    ]

    try:
        m = json.loads(meta)
        if m.get("annotations"):
            header.append(f"Annotations: {', '.join(m['annotations'])}")
        if m.get("http_path"):
            header.append(f"API Endpoint: {m['http_path']}")
    except: pass

    output_lines = [
        "\n".join(header),
        "--------------------------------------------------"
    ]

    if doc:
        output_lines.append(f"/* DOCSTRING */\n{doc}\n")

    output_lines.append(block['content'])
    output_lines.append("--------------------------------------------------")

    output = "\n".join(output_lines)

    def build_pack() -> str:
        lines = [pack_header("read_symbol", {}, returned=1)]
        lines.append(pack_line("t", single_value=pack_encode_text(output)))
        return "\n".join(lines)

    return mcp_response(
        "read_symbol",
        build_pack,
        lambda: {"content": [{"type": "text", "text": output}]},
    )
