import json
from typing import Any, Dict, List
try:
    from ._util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode
except ImportError:
    from _util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode

def execute_get_callers(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    """Find symbols that call a specific symbol."""
    target_symbol = args.get("name", "").strip()
    target_sid = args.get("symbol_id", "").strip() or args.get("sid", "").strip()
    if not target_symbol and not target_sid:
        return mcp_response(
            "get_callers",
            lambda: pack_error("get_callers", ErrorCode.INVALID_ARGS, "Symbol name or symbol_id is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "Symbol name or symbol_id is required"}, "isError": True},
        )

    # Search in symbol_relations table
    params = []
    if target_sid:
        sql = """
            SELECT from_path, from_symbol, from_symbol_id, line, rel_type
            FROM symbol_relations
            WHERE to_symbol_id = ?
            ORDER BY from_path, line
        """
        params.append(target_sid)
    else:
        sql = """
            SELECT from_path, from_symbol, from_symbol_id, line, rel_type
            FROM symbol_relations
            WHERE to_symbol = ?
            ORDER BY from_path, line
        """
        params.append(target_symbol)
    root_ids = resolve_root_ids(roots)
    if root_ids:
        root_clause = " OR ".join(["from_path LIKE ?"] * len(root_ids))
        sql = sql.replace("ORDER BY", f"AND ({root_clause}) ORDER BY")
        params.extend([f"{rid}/%" for rid in root_ids])

    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        # Fallback for legacy schema without symbol_id columns
        sql = """
            SELECT from_path, from_symbol, line, rel_type
            FROM symbol_relations
            WHERE to_symbol = ?
            ORDER BY from_path, line
        """
        params = [target_symbol]
        if root_ids:
            root_clause = " OR ".join(["from_path LIKE ?"] * len(root_ids))
            sql = sql.replace("ORDER BY", f"AND ({root_clause}) ORDER BY")
            params.extend([f"{rid}/%" for rid in root_ids])
        rows = conn.execute(sql, params).fetchall()

    results = []
    for r in rows:
        caller_sid = ""
        try:
            if hasattr(r, "keys") and "from_symbol_id" in r.keys():
                caller_sid = r["from_symbol_id"]
        except Exception:
            caller_sid = ""
        results.append({
            "caller_path": r["from_path"],
            "caller_symbol": r["from_symbol"],
            "caller_symbol_id": caller_sid,
            "line": r["line"],
            "rel_type": r["rel_type"]
        })

    def build_pack() -> str:
        lines = [pack_header("get_callers", {"name": pack_encode_text(target_symbol), "sid": pack_encode_id(target_sid)}, returned=len(results))]
        for r in results:
            kv = {
                "caller_path": pack_encode_id(r["caller_path"]),
                "caller_symbol": pack_encode_id(r["caller_symbol"]),
                "caller_sid": pack_encode_id(r.get("caller_symbol_id", "")),
                "line": str(r["line"]),
                "rel_type": pack_encode_id(r["rel_type"]),
            }
            lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "get_callers",
        build_pack,
        lambda: {"target": target_symbol, "target_sid": target_sid, "results": results, "count": len(results)},
    )
