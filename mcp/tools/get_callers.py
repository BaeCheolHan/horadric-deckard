from typing import Any, Dict, List

def execute_get_callers(args: Dict[str, Any], db: Any) -> Dict[str, Any]:
    """Find symbols that call a specific symbol."""
    target_symbol = args.get("name", "").strip()
    if not target_symbol:
        return {"results": [], "error": "Symbol name is required"}

    # Search in symbol_relations table
    sql = """
        SELECT from_path, from_symbol, line, rel_type
        FROM symbol_relations
        WHERE to_symbol = ?
        ORDER BY from_path, line
    """
    params = [target_symbol]
    
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

    return {
        "target": target_symbol,
        "results": results,
        "count": len(results)
    }
