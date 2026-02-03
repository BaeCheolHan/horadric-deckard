import json
from typing import Any, Dict, List
try:
    from ._util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode
except ImportError:
    from _util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode

def execute_get_implementations(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    """Find symbols that implement or extend a specific symbol."""
    target_symbol = args.get("name", "").strip()
    if not target_symbol:
        return mcp_response(
            "get_implementations",
            lambda: pack_error("get_implementations", ErrorCode.INVALID_ARGS, "Symbol name is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "Symbol name is required"}, "isError": True},
        )

    # Search in symbol_relations table for implements and extends relations
    sql = """
        SELECT from_path, from_symbol, rel_type, line
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
    
    with db._read_lock:
        rows = db._read.execute(sql, params).fetchall()

    results = []
    for r in rows:
        results.append({
            "implementer_path": r["from_path"],
            "implementer_symbol": r["from_symbol"],
            "rel_type": r["rel_type"],
            "line": r["line"]
        })

    def build_pack() -> str:
        lines = [pack_header("get_implementations", {"name": pack_encode_text(target_symbol)}, returned=len(results))]
        for r in results:
            kv = {
                "implementer_path": pack_encode_id(r["implementer_path"]),
                "implementer_symbol": pack_encode_id(r["implementer_symbol"]),
                "rel_type": pack_encode_id(r["rel_type"]),
                "line": str(r["line"]),
            }
            lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "get_implementations",
        build_pack,
        lambda: {"target": target_symbol, "results": results, "count": len(results)},
    )
