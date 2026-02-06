import json
from typing import Any, Dict, List
from sari.mcp.tools._util import (
    mcp_response,
    pack_header,
    pack_line,
    pack_encode_id,
    pack_encode_text,
    resolve_root_ids,
    resolve_repo_scope,
    pack_error,
    ErrorCode,
)
from sari.mcp.tools.call_graph import build_call_graph

def execute_get_callers(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    """Find symbols that call a specific symbol."""
    target_symbol = args.get("name", "").strip()
    target_sid = args.get("symbol_id", "").strip() or args.get("sid", "").strip()
    target_path = str(args.get("path", "")).strip()
    repo = str(args.get("repo", "")).strip()
    limit = max(1, min(int(args.get("limit", 100) or 100), 500))
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
    allowed_root_ids = resolve_root_ids(roots)
    req_root_ids = args.get("root_ids")
    if isinstance(req_root_ids, list) and req_root_ids:
        req_set = {str(x) for x in req_root_ids if x}
        effective_root_ids = [rid for rid in allowed_root_ids if rid in req_set]
    else:
        effective_root_ids = allowed_root_ids

    _, repo_root_ids = resolve_repo_scope(repo, roots, db=db)
    if repo_root_ids:
        repo_set = set(repo_root_ids)
        effective_root_ids = [rid for rid in effective_root_ids if rid in repo_set] if effective_root_ids else list(repo_root_ids)

    if effective_root_ids:
        root_clause = " OR ".join(["from_path LIKE ?"] * len(effective_root_ids))
        sql = sql.replace("ORDER BY", f"AND ({root_clause}) ORDER BY")
        params.extend([f"{rid}/%" for rid in effective_root_ids])
    if target_path:
        sql = sql.replace("ORDER BY", "AND (to_path = ? OR to_path = '' OR to_path IS NULL) ORDER BY")
        params.append(target_path)
    sql += " LIMIT ?"
    params.append(limit)

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
        if effective_root_ids:
            root_clause = " OR ".join(["from_path LIKE ?"] * len(effective_root_ids))
            sql = sql.replace("ORDER BY", f"AND ({root_clause}) ORDER BY")
            params.extend([f"{rid}/%" for rid in effective_root_ids])
        if target_path:
            sql = sql.replace("ORDER BY", "AND (to_path = ? OR to_path = '' OR to_path IS NULL) ORDER BY")
            params.append(target_path)
        sql += " LIMIT ?"
        params.append(limit)
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

    if not results:
        try:
            graph = build_call_graph(
                {"symbol": target_symbol, "symbol_id": target_sid, "path": target_path, "depth": 1, "include_paths": [f"/{repo}/"] if repo else []},
                db,
                roots,
            )
            children = ((graph.get("upstream") or {}).get("children") or [])[:limit]
            for c in children:
                results.append(
                    {
                        "caller_path": c.get("path", ""),
                        "caller_symbol": c.get("name", ""),
                        "caller_symbol_id": c.get("symbol_id", ""),
                        "line": int(c.get("line", 0) or 0),
                        "rel_type": c.get("rel_type", "calls_heuristic"),
                    }
                )
        except Exception:
            pass

    def build_pack() -> str:
        lines = [pack_header("get_callers", {"name": pack_encode_text(target_symbol), "sid": pack_encode_id(target_sid), "path": pack_encode_id(target_path), "repo": pack_encode_id(repo)}, returned=len(results))]
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
