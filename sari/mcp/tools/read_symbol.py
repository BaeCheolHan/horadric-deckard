#!/usr/bin/env python3
"""
Read Symbol Tool for Local Search MCP Server.
Reads only the specific code block (function/class) of a symbol.
"""
import json
import time
from typing import Any, Dict, List, Optional

from sari.core.db import LocalSearchDB
from sari.mcp.telemetry import TelemetryLogger
from sari.mcp.tools._util import (
    mcp_response,
    pack_error,
    ErrorCode,
    resolve_db_path,
    resolve_root_ids,
    pack_header,
    pack_line,
    pack_encode_text,
    pack_encode_id,
)


def _extract_block_from_lines(content: str, start_line: int, end_line: int) -> str:
    lines = content.splitlines()
    if not lines:
        return ""
    s = max(1, int(start_line or 1))
    e = max(s, int(end_line or s))
    if s > len(lines):
        return ""
    return "\n".join(lines[s - 1 : min(e, len(lines))])


def _symbol_candidates(
    db: LocalSearchDB,
    name: str,
    symbol_id: str,
    db_path: Optional[str],
    roots: List[str],
    limit: int = 50,
) -> List[Dict[str, Any]]:
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    params: List[Any] = []
    sql = "SELECT symbol_id, path, name, kind, line, end_line, qualname FROM symbols WHERE 1=1"
    if symbol_id:
        sql += " AND symbol_id = ?"
        params.append(symbol_id)
    elif name:
        sql += " AND name = ?"
        params.append(name)
    if db_path:
        sql += " AND path = ?"
        params.append(db_path)
    root_ids = resolve_root_ids(roots)
    if root_ids:
        sql += " AND (" + " OR ".join(["path LIKE ?"] * len(root_ids)) + ")"
        params.extend([f"{rid}/%" for rid in root_ids])
    sql += " ORDER BY path, line LIMIT ?"
    params.append(max(1, min(int(limit or 50), 200)))
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def execute_read_symbol(args: Dict[str, Any], db: LocalSearchDB, logger: TelemetryLogger, roots: List[str]) -> Dict[str, Any]:
    """Execute read_symbol tool."""
    start_ts = time.time()

    path = str(args.get("path") or "").strip() or None
    symbol_name = str(args.get("name") or "").strip()
    symbol_id = str(args.get("symbol_id") or args.get("sid") or "").strip()

    if not symbol_name and not symbol_id:
        return mcp_response(
            "read_symbol",
            lambda: pack_error("read_symbol", ErrorCode.INVALID_ARGS, "'name' or 'symbol_id' is required."),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "'name' or 'symbol_id' is required."}, "isError": True},
        )

    db_path = resolve_db_path(path, roots) if path else None
    if not db_path and db.has_legacy_paths():
        db_path = path
    if path and not db_path:
        return mcp_response(
            "read_symbol",
            lambda: pack_error("read_symbol", ErrorCode.ERR_ROOT_OUT_OF_SCOPE, f"Path out of scope: {path}", hints=["outside final_roots"]),
            lambda: {"error": {"code": ErrorCode.ERR_ROOT_OUT_OF_SCOPE.value, "message": f"Path out of scope: {path}"}, "isError": True},
        )

    candidates = _symbol_candidates(db, symbol_name, symbol_id, db_path, roots, limit=args.get("limit", 50))
    if not candidates:
        return mcp_response(
            "read_symbol",
            lambda: pack_error("read_symbol", ErrorCode.NOT_INDEXED, "Symbol not found in current index."),
            lambda: {"error": {"code": ErrorCode.NOT_INDEXED.value, "message": "Symbol not found in current index."}, "isError": True},
        )

    if len(candidates) > 1 and not db_path and not symbol_id:
        preview = candidates[:20]

        def build_pack_multi() -> str:
            lines = [pack_header("read_symbol", {"name": pack_encode_id(symbol_name)}, returned=len(preview))]
            lines.append(pack_line("m", {"needs_disambiguation": "true", "count": str(len(candidates))}))
            for c in preview:
                lines.append(
                    pack_line(
                        "r",
                        {
                            "sid": pack_encode_id(c.get("symbol_id", "")),
                            "name": pack_encode_id(c.get("name", "")),
                            "kind": pack_encode_id(c.get("kind", "")),
                            "path": pack_encode_id(c.get("path", "")),
                            "line": str(c.get("line", 0)),
                            "qual": pack_encode_id(c.get("qualname", "")),
                        },
                    )
                )
            return "\n".join(lines)

        return mcp_response(
            "read_symbol",
            build_pack_multi,
            lambda: {"needs_disambiguation": True, "count": len(candidates), "candidates": candidates},
        )

    target = candidates[0]
    target_path = str(target.get("path", ""))
    start_line = int(target.get("line", 0) or 0)
    end_line = int(target.get("end_line", 0) or start_line)
    full_content = db.read_file(target_path) or ""
    block = _extract_block_from_lines(full_content, start_line, end_line)
    if not block:
        block = db.get_symbol_block(target_path, str(target.get("name", symbol_name))) or ""

    latency_ms = int((time.time() - start_ts) * 1000)
    if logger:
        logger.log_telemetry(
            f"tool=read_symbol path='{target_path}' name='{target.get('name', symbol_name)}' sid='{target.get('symbol_id', symbol_id)}' found={bool(block)} latency={latency_ms}ms"
        )

    if not block:
        return mcp_response(
            "read_symbol",
            lambda: pack_error("read_symbol", ErrorCode.NOT_INDEXED, "Symbol range exists but content block extraction failed."),
            lambda: {"error": {"code": ErrorCode.NOT_INDEXED.value, "message": "Symbol range exists but content block extraction failed."}, "isError": True},
        )

    block_dict = {
        "name": str(target.get("name", symbol_name)),
        "path": target_path,
        "start_line": start_line,
        "end_line": end_line,
        "content": block,
        "docstring": "",
        "metadata": "{}",
        "symbol_id": str(target.get("symbol_id", symbol_id)),
        "kind": str(target.get("kind", "")),
        "qualname": str(target.get("qualname", "")),
    }

    doc = block_dict.get("docstring", "")
    meta = block_dict.get("metadata", "{}")
    content = str(block_dict.get("content", ""))

    def build_pack() -> str:
        lines = [pack_header("read_symbol", {}, returned=1)]
        lines.append(pack_line("s", {
            "name": pack_encode_id(block_dict.get("name", symbol_name)),
            "sid": pack_encode_id(block_dict.get("symbol_id", "")),
            "kind": pack_encode_id(block_dict.get("kind", "")),
            "qual": pack_encode_id(block_dict.get("qualname", "")),
            "path": pack_encode_id(block_dict.get("path", "")),
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
            "path": target_path,
            "name": block_dict.get("name", symbol_name),
            "symbol_id": block_dict.get("symbol_id", ""),
            "kind": block_dict.get("kind", ""),
            "qualname": block_dict.get("qualname", ""),
            "start_line": block_dict.get("start_line", 0),
            "end_line": block_dict.get("end_line", 0),
            "content": content,
            "docstring": doc,
            "metadata": meta_json,
        },
    )
