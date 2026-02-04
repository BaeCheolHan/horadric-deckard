import json
import sqlite3
from typing import Any, Dict, List
try:
    from ._util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode
except ImportError:
    from _util import mcp_response, pack_header, pack_line, pack_encode_id, pack_encode_text, resolve_root_ids, pack_error, ErrorCode

def execute_search_api_endpoints(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    """Search for API endpoints by URL path pattern."""
    path_query = args.get("path", "").strip()
    if not path_query:
        return mcp_response(
            "search_api_endpoints",
            lambda: pack_error("search_api_endpoints", ErrorCode.INVALID_ARGS, "Path query is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "Path query is required"}, "isError": True},
        )

    # Search in symbols where metadata contains the path
    # SQLite JSON support is limited in older versions, so we use LIKE on metadata TEXT
    sql = """
        SELECT path, name, kind, line, metadata, content
        FROM symbols
        WHERE metadata LIKE ? AND (kind = 'method' OR kind = 'function' OR kind = 'class')
    """
    # Look for partial matches in metadata (looser LIKE, filter in Python)
    params = [f'%{path_query}%']
    root_ids = resolve_root_ids(roots)
    if root_ids:
        root_clause = " OR ".join(["path LIKE ?"] * len(root_ids))
        sql += f" AND ({root_clause})"
        params.extend([f"{rid}/%" for rid in root_ids])

    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    rows = conn.execute(sql, params).fetchall()

    results = []
    for r in rows:
        try:
            meta = json.loads(r["metadata"])
            http_path = meta.get("http_path", "")
            if path_query in http_path or path_query == http_path:
                results.append({
                    "path": r["path"],
                    "name": r["name"],
                    "kind": r["kind"],
                    "line": r["line"],
                    "http_path": http_path,
                    "annotations": meta.get("annotations", []),
                    "snippet": r["content"]
                })
        except:
            continue

    def build_pack() -> str:
        lines = [pack_header("search_api_endpoints", {"q": pack_encode_text(path_query)}, returned=len(results))]
        for r in results:
            kv = {
                "path": pack_encode_id(r["path"]),
                "name": pack_encode_id(r["name"]),
                "kind": pack_encode_id(r["kind"]),
                "line": str(r["line"]),
                "http_path": pack_encode_text(r["http_path"]),
            }
            lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "search_api_endpoints",
        build_pack,
        lambda: {"query": path_query, "results": results, "count": len(results)},
    )
