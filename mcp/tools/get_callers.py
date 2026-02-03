import json
from typing import Any, Dict, List
try:
    from ._util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode
except ImportError:
    from _util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode

def execute_get_callers(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    """Find symbols that call a specific symbol."""
    target_symbol = args.get("name", "").strip()
    if not target_symbol:
        return mcp_response(
            "get_callers",
            lambda: pack_error("get_callers", ErrorCode.INVALID_ARGS, "Symbol name is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "Symbol name is required"}, "isError": True},
        )

    # Search in symbol_relations table
    sql = """
        SELECT from_path, from_symbol, line, rel_type
        FROM symbol_relations
        WHERE to_symbol = ?
        ORDER BY from_path, line
    """
    params = [target_symbol]
    root_ids = resolve_root_ids(roots)
    if root_ids:
        root_clause = " OR ".join(["from_path LIKE ?"] * len(root_ids))
        sql = sql.replace("ORDER BY", f"AND ({root_clause}) ORDER BY")
        params.extend([f"{rid}/%" for rid in root_ids])
    
    with db._read_lock:
        rows = db._read.execute(sql, params).fetchall()

    results = []
    for r in rows:
        results.append({
            "caller_path": r["from_path"],
            "caller_symbol": r["from_symbol"],
            "line": r["line"],
            "rel_type": r["rel_type"]
        })

    def build_pack() -> str:
        lines = [pack_header("get_callers", {"name": pack_encode_text(target_symbol)}, returned=len(results))]
        for r in results:
            kv = {
                "caller_path": pack_encode_id(r["caller_path"]),
                "caller_symbol": pack_encode_id(r["caller_symbol"]),
                "line": str(r["line"]),
                "rel_type": pack_encode_id(r["rel_type"]),
            }
            lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "get_callers",
        build_pack,
        lambda: {"target": target_symbol, "results": results, "count": len(results)},
    )
