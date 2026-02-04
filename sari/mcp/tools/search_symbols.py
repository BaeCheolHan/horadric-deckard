from typing import Any, Dict, List, Optional
from sari.core.db import LocalSearchDB
from sari.mcp.tools._util import mcp_response, pack_header, pack_line, pack_truncated, pack_encode_id, pack_encode_text, resolve_root_ids


def _precision_hint(path: str) -> str:
    ext = (path or "").lower().rsplit(".", 1)
    if len(ext) == 2:
        ext = f".{ext[1]}"
    else:
        ext = ""
    if ext == ".py":
        return "high (AST)"
    if ext in {".js", ".jsx"}:
        return "low (regex JS)"
    if ext in {".ts", ".tsx"}:
        return "low (regex TS)"
    if ext == ".java":
        return "low (regex Java)"
    if ext == ".kt":
        return "low (regex Kotlin)"
    if ext == ".go":
        return "low (regex Go)"
    if ext in {".c", ".h"}:
        return "low (regex C/C++)"
    if ext == ".cpp":
        return "low (regex C++)"
    return "medium"

def execute_search_symbols(args: Dict[str, Any], db: LocalSearchDB, roots: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Execute search_symbols tool.

    Args:
        args: {"query": str, "limit": int}
        db: LocalSearchDB instance
    """
    query = args.get("query", "")
    limit_arg = int(args.get("limit", 20))
    root_ids = resolve_root_ids(list(roots or []))

    # --- JSON Builder (Legacy/Debug) ---
    def build_json() -> Dict[str, Any]:
        results = db.search_symbols(query, limit=limit_arg, root_ids=root_ids)
        return {
            "query": query,
            "count": len(results),
            "symbols": [
                dict(r, precision_hint=_precision_hint(r.get("path", "")))
                for r in results
            ],
        }

    # --- PACK1 Builder ---
    def build_pack() -> str:
        # Hard limit for PACK1: 50
        pack_limit = min(limit_arg, 50)

        results = db.search_symbols(query, limit=pack_limit, root_ids=root_ids)
        returned = len(results)

        # Header
        # Note: search_symbols DB query typically doesn't return total count currently
        kv = {"q": pack_encode_text(query), "limit": pack_limit}
        lines = [
            pack_header("search_symbols", kv, returned=returned, total_mode="none")
        ]

        # Records
        for r in results:
            # h:repo=<repo> path=<path> line=<line> kind=<kind> name=<name>
            # repo, path, name, kind => ENC_ID (identifiers)
            kv_line = {
                "repo": pack_encode_id(r["repo"]),
                "path": pack_encode_id(r["path"]),
                "line": str(r["line"]),
                "kind": pack_encode_id(r["kind"]),
                "name": pack_encode_id(r["name"]),
                "qual": pack_encode_id(r.get("qualname", "")),
                "sid": pack_encode_id(r.get("symbol_id", "")),
                "precision": pack_encode_text(_precision_hint(r.get("path", ""))),
            }
            lines.append(pack_line("h", kv_line))

        # Truncation
        # Since we don't know total, if we hit the limit, we say truncated=maybe
        if returned >= pack_limit:
            # next offset is unknown/not supported by simple symbol search usually,
            # but we follow the format. offset=returned is best guess if paginated.
            lines.append(pack_truncated(returned, pack_limit, "maybe"))

        return "\n".join(lines)

    return mcp_response("search_symbols", build_pack, build_json)
