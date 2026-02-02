import json
import sqlite3
from typing import Any, Dict, List

def execute_search_api_endpoints(args: Dict[str, Any], db: Any) -> Dict[str, Any]:
    """Search for API endpoints by URL path pattern."""
    path_query = args.get("path", "").strip()
    if not path_query:
        return {"results": [], "error": "Path query is required"}

    # Search in symbols where metadata contains the path
    # SQLite JSON support is limited in older versions, so we use LIKE on metadata TEXT
    sql = """
        SELECT path, name, kind, line, metadata, content
        FROM symbols
        WHERE metadata LIKE ? AND (kind = 'method' OR kind = 'function' OR kind = 'class')
    """
    # Look for partial matches in metadata (looser LIKE, filter in Python)
    params = [f'%{path_query}%']
    
    with db._read_lock:
        rows = db._read.execute(sql, params).fetchall()

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

    return {
        "query": path_query,
        "results": results,
        "count": len(results)
    }
