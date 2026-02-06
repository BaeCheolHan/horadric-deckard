from typing import Any, Dict, List
from sari.core.db import LocalSearchDB
from sari.mcp.tools._util import (
    ErrorCode,
    mcp_response,
    pack_error,
    pack_header,
    pack_line,
    pack_truncated,
    pack_encode_id,
    pack_encode_text,
    resolve_root_ids,
    resolve_repo_scope,
)


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

def execute_search_symbols(args: Dict[str, Any], db: LocalSearchDB, logger: Any, roots: List[str]) -> Dict[str, Any]:
    """
    Execute search_symbols tool.

    Args:
        args: {"query": str, "limit": int}
        db: LocalSearchDB instance
    """
    query = str(args.get("query", "")).strip()
    if not query:
        return {
            "content": [{
                "type": "text",
                "text": pack_error(
                    "search_symbols",
                    ErrorCode.INVALID_ARGS,
                    "query is required",
                    hints=["Provide a non-empty query string."],
                ),
            }],
            "isError": True,
        }

    try:
        limit_arg = int(args.get("limit", 20))
    except Exception:
        limit_arg = 20
    limit_arg = max(1, min(limit_arg, 200))

    allowed_root_ids = resolve_root_ids(roots)
    req_root_ids = args.get("root_ids")
    if isinstance(req_root_ids, list) and req_root_ids:
        req_set = {str(x) for x in req_root_ids if x}
        root_ids = [rid for rid in allowed_root_ids if rid in req_set]
    else:
        root_ids = allowed_root_ids

    repo_arg = str(args.get("repo", "")).strip() or None
    repo, repo_root_ids = resolve_repo_scope(repo_arg, roots, db=db)
    if repo_root_ids:
        root_ids = [rid for rid in root_ids if rid in set(repo_root_ids)] if root_ids else list(repo_root_ids)
    path_prefix = str(args.get("path_prefix", "")).strip() or None
    kinds_arg = args.get("kinds")
    single_kind = str(args.get("kind", "")).strip()
    if isinstance(kinds_arg, str):
        kinds = [kinds_arg] if kinds_arg.strip() else []
    elif isinstance(kinds_arg, list):
        kinds = [str(x).strip() for x in kinds_arg if str(x).strip()]
    else:
        kinds = []
    if single_kind:
        kinds.append(single_kind)
    kinds = list(dict.fromkeys(kinds))
    match_mode = str(args.get("match_mode", "contains")).strip().lower()
    if match_mode not in {"contains", "prefix", "exact"}:
        match_mode = "contains"
    include_qualname = bool(args.get("include_qualname", True))
    case_sensitive = bool(args.get("case_sensitive", False))

    q_cmp = query if case_sensitive else query.lower()

    def _score_row(r: Dict[str, Any]) -> int:
        n = str(r.get("name", ""))
        qn = str(r.get("qualname", ""))
        n_cmp = n if case_sensitive else n.lower()
        qn_cmp = qn if case_sensitive else qn.lower()
        if n_cmp == q_cmp:
            return 100
        if qn_cmp == q_cmp:
            return 95
        if n_cmp.startswith(q_cmp):
            return 80
        if qn_cmp.startswith(q_cmp):
            return 75
        if q_cmp in n_cmp:
            return 60
        if q_cmp in qn_cmp:
            return 55
        return 10

    # --- JSON Builder (Legacy/Debug) ---
    def build_json() -> Dict[str, Any]:
        results = db.search_symbols(
            query,
            limit=limit_arg,
            root_ids=root_ids,
            repo=repo,
            kinds=kinds,
            path_prefix=path_prefix,
            match_mode=match_mode,
            include_qualname=include_qualname,
            case_sensitive=case_sensitive,
        )
        results = sorted(results, key=lambda r: (-_score_row(r), r.get("path", ""), int(r.get("line", 0))))
        return {
            "query": query,
            "count": len(results),
            "filters": {
                "repo": repo,
                "kinds": kinds,
                "path_prefix": path_prefix,
                "match_mode": match_mode,
                "include_qualname": include_qualname,
                "case_sensitive": case_sensitive,
            },
            "symbols": [
                dict(r, precision_hint=_precision_hint(r.get("path", "")))
                for r in results
            ],
        }

    # --- PACK1 Builder ---
    def build_pack() -> str:
        # Hard limit for PACK1: 50
        pack_limit = min(limit_arg, 50)

        results = db.search_symbols(
            query,
            limit=pack_limit,
            root_ids=root_ids,
            repo=repo,
            kinds=kinds,
            path_prefix=path_prefix,
            match_mode=match_mode,
            include_qualname=include_qualname,
            case_sensitive=case_sensitive,
        )
        results = sorted(results, key=lambda r: (-_score_row(r), r.get("path", ""), int(r.get("line", 0))))
        returned = len(results)

        # Header
        # Note: search_symbols DB query typically doesn't return total count currently
        kv = {
            "q": pack_encode_text(query),
            "limit": pack_limit,
            "mode": pack_encode_id(match_mode),
            "case": "sensitive" if case_sensitive else "insensitive",
        }
        if repo:
            kv["repo"] = pack_encode_id(repo)
        if kinds:
            kv["kinds"] = pack_encode_text(",".join(kinds))
        if path_prefix:
            kv["path_prefix"] = pack_encode_id(path_prefix)
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
                "score": str(_score_row(r)),
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
