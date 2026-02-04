import json
from typing import Any, Dict, List
try:
    from ._util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode
except ImportError:
    from _util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode

def execute_get_implementations(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    """Find symbols that implement or extend a specific symbol."""
    target_symbol = args.get("name", "").strip()
    target_sid = args.get("symbol_id", "").strip() or args.get("sid", "").strip()
    if not target_symbol and not target_sid:
        return mcp_response(
            "get_implementations",
            lambda: pack_error("get_implementations", ErrorCode.INVALID_ARGS, "Symbol name or symbol_id is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "Symbol name or symbol_id is required"}, "isError": True},
        )

    # Search in symbol_relations table for implements and extends relations
    if target_sid:
        sql = """
            SELECT from_path, from_symbol, from_symbol_id, rel_type, line
            FROM symbol_relations
            WHERE to_symbol_id = ? AND (rel_type = 'implements' OR rel_type = 'extends')
            ORDER BY from_path, line
        """
        params = [target_sid]
    else:
        sql = """
            SELECT from_path, from_symbol, from_symbol_id, rel_type, line
            FROM symbol_relations
            WHERE to_symbol = ? AND (rel_type = 'implements' OR rel_type = 'extends')
            ORDER BY from_path, line
        """
        params = [target_symbol]
    root_ids = resolve_root_ids(roots)
    if root_ids:
        root_clause = " OR ".join(["from_path LIKE ?"] * len(root_ids))
        sql = sql.replace("ORDER BY", f"AND ({root_clause}) ORDER BY")
        params.extend([f"{rid}/%" for rid in root_ids])

    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        sql = """
            SELECT from_path, from_symbol, rel_type, line
            FROM symbol_relations
            WHERE to_symbol = ? AND (rel_type = 'implements' OR rel_type = 'extends')
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
        impl_sid = ""
        try:
            if hasattr(r, "keys") and "from_symbol_id" in r.keys():
                impl_sid = r["from_symbol_id"]
        except Exception:
            impl_sid = ""
        results.append({
            "implementer_path": r["from_path"],
            "implementer_symbol": r["from_symbol"],
            "implementer_symbol_id": impl_sid,
            "rel_type": r["rel_type"],
            "line": r["line"]
        })

    def build_pack() -> str:
        lines = [pack_header("get_implementations", {"name": pack_encode_text(target_symbol), "sid": pack_encode_id(target_sid)}, returned=len(results))]
        for r in results:
            kv = {
                "implementer_path": pack_encode_id(r["implementer_path"]),
                "implementer_symbol": pack_encode_id(r["implementer_symbol"]),
                "implementer_sid": pack_encode_id(r.get("implementer_symbol_id", "")),
                "rel_type": pack_encode_id(r["rel_type"]),
                "line": str(r["line"]),
            }
            lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "get_implementations",
        build_pack,
        lambda: {"target": target_symbol, "target_sid": target_sid, "results": results, "count": len(results)},
    )
