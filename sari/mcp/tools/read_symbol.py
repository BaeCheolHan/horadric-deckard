#!/usr/bin/env python3
"""
Read Symbol Tool for Local Search MCP Server.
Reads only the specific code block (function/class) of a symbol.
"""
import json
import time
from typing import Any, Dict, List

from sari.core.db import LocalSearchDB
from sari.mcp.telemetry import TelemetryLogger
from sari.mcp.tools._util import mcp_response, pack_error, ErrorCode, resolve_db_path, pack_header, pack_line, pack_encode_text, pack_encode_id


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

    if isinstance(block, str):
        block_dict = {
            "name": symbol_name,
            "path": db_path,
            "start_line": 0,
            "end_line": 0,
            "content": block,
            "docstring": "",
            "metadata": "{}",
        }
    else:
        block_dict = dict(block)

    doc = block_dict.get("docstring", "")
    meta = block_dict.get("metadata", "{}")
    content = str(block_dict.get("content", ""))

    def build_pack() -> str:
        lines = [pack_header("read_symbol", {}, returned=1)]
        lines.append(pack_line("s", {
            "name": pack_encode_id(block_dict.get("name", symbol_name)),
            "path": pack_encode_id(block_dict.get("path", db_path)),
            "start": str(block_dict.get("start_line", 0)),
            "end": str(block_dict.get("end_line", 0)),
        }))
        if doc:
            lines.append(pack_line("d", single_value=pack_encode_text(doc)))
        lines.append(pack_line("c", single_value=pack_encode_text(content)))
        return "\n".join(lines)

    try:
        meta_json = json.loads(meta) if isinstance(meta, str) and meta else meta
    except Exception:
        meta_json = {}

    return mcp_response(
        "read_symbol",
        build_pack,
        lambda: {
            "path": db_path,
            "name": block_dict.get("name", symbol_name),
            "start_line": block_dict.get("start_line", 0),
            "end_line": block_dict.get("end_line", 0),
            "content": content,
            "docstring": doc,
            "metadata": meta_json,
        },
    )
