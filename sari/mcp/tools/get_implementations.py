import json
import re
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

def execute_get_implementations(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    """Find symbols that implement or extend a specific symbol."""
    target_symbol = args.get("name", "").strip()
    target_sid = args.get("symbol_id", "").strip() or args.get("sid", "").strip()
    target_path = str(args.get("path", "")).strip()
    repo = str(args.get("repo", "")).strip()
    limit = max(1, min(int(args.get("limit", 100) or 100), 500))
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
        sql = """
            SELECT from_path, from_symbol, rel_type, line
            FROM symbol_relations
            WHERE to_symbol = ? AND (rel_type = 'implements' OR rel_type = 'extends')
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

    if not results and target_symbol:
        # Heuristic fallback using file contents (schema-independent).
        like_patterns = [f"%implements {target_symbol}%", f"%extends {target_symbol}%"]
        h_sql = "SELECT path, content FROM files WHERE (content LIKE ? OR content LIKE ?)"
        h_params: List[Any] = [like_patterns[0], like_patterns[1]]
        if effective_root_ids:
            h_sql += " AND (" + " OR ".join(["path LIKE ?"] * len(effective_root_ids)) + ")"
            h_params.extend([f"{rid}/%" for rid in effective_root_ids])
        h_sql += " ORDER BY path LIMIT ?"
        h_params.append(limit)
        try:
            h_rows = conn.execute(h_sql, h_params).fetchall()
            for r in h_rows:
                file_path = r["path"]
                text = r["content"] or ""
                if isinstance(text, bytes):
                    text = text.decode("utf-8", errors="ignore")
                rel_type = "implements" if re.search(rf"\\bimplements\\s+{re.escape(target_symbol)}\\b", text) else "extends"
                m = re.search(rf"\\b(implements|extends)\\s+{re.escape(target_symbol)}\\b", text)
                line = text.count("\\n", 0, m.start()) + 1 if m else 0
                sym = conn.execute(
                    "SELECT symbol_id, name, line FROM symbols WHERE path = ? ORDER BY line LIMIT 1",
                    (file_path,),
                ).fetchone()
                results.append(
                    {
                        "implementer_path": file_path,
                        "implementer_symbol": (sym["name"] if sym else "__file__"),
                        "implementer_symbol_id": (sym["symbol_id"] if sym else ""),
                        "rel_type": rel_type,
                        "line": int(line or (sym["line"] if sym else 0) or 0),
                    }
                )
        except Exception:
            pass

    def build_pack() -> str:
        lines = [pack_header("get_implementations", {"name": pack_encode_text(target_symbol), "sid": pack_encode_id(target_sid), "path": pack_encode_id(target_path), "repo": pack_encode_id(repo)}, returned=len(results))]
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
