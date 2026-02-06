import json
import os
import importlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, Callable

from sari.mcp.tools._util import (
    mcp_response,
    pack_header,
    pack_line,
    pack_encode_id,
    pack_encode_text,
    pack_error,
    ErrorCode,
    resolve_root_ids,
)


def _resolve_symbol(db: Any, name: str, path: Optional[str], symbol_id: Optional[str]) -> List[Dict[str, Any]]:
    params: List[Any] = []
    if symbol_id:
        sql = """
            SELECT path, name, kind, line, end_line, qualname, symbol_id
            FROM symbols
            WHERE symbol_id = ?
        """
        params.append(symbol_id)
    else:
        sql = """
            SELECT path, name, kind, line, end_line, qualname, symbol_id
            FROM symbols
            WHERE name = ?
        """
        params.append(name)
    if path:
        sql += " AND path = ?"
        params.append(path)
    sql += " ORDER BY path, line LIMIT 50"
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _callers_for(db: Any, name: str, path: Optional[str], symbol_id: Optional[str]) -> List[Dict[str, Any]]:
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    if symbol_id:
        params: List[Any] = [symbol_id]
        sql = """
            SELECT from_path, from_symbol, from_symbol_id, line, rel_type
            FROM symbol_relations
            WHERE to_symbol_id = ?
        """
        if path:
            sql += " AND (to_path = ? OR to_path = '' OR to_path IS NULL)"
            params.append(path)
        sql += " ORDER BY from_path, line"
        try:
            rows = conn.execute(sql, params).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass
    params = [name]
    sql = """
        SELECT from_path, from_symbol, from_symbol_id, line, rel_type
        FROM symbol_relations
        WHERE to_symbol = ?
    """
    if path:
        sql += " AND (to_path = ? OR to_path = '' OR to_path IS NULL)"
        params.append(path)
    sql += " ORDER BY from_path, line"
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        rows = []
    neighbors = [dict(r) for r in rows]
    if not neighbors and name:
        neighbors = _heuristic_callers(db, name, path, symbol_id)
        if neighbors:
            _HEUR_CACHE["up"] = True
    neighbors, enriched = _enrich_neighbors(db, neighbors, "up")
    _REL_DENSITY["up"] += len(neighbors)
    if enriched:
        _ENRICH_CACHE["up"] = True
    return _apply_plugin("up", neighbors, {"name": name, "path": path, "symbol_id": symbol_id})


def _callees_for(db: Any, name: str, path: Optional[str], symbol_id: Optional[str]) -> List[Dict[str, Any]]:
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    if symbol_id:
        params: List[Any] = [symbol_id]
        sql = """
            SELECT to_path, to_symbol, to_symbol_id, line, rel_type
            FROM symbol_relations
            WHERE from_symbol_id = ?
        """
        if path:
            sql += " AND from_path = ?"
            params.append(path)
        sql += " ORDER BY to_path, line"
        try:
            rows = conn.execute(sql, params).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass
    params = [name]
    sql = """
        SELECT to_path, to_symbol, to_symbol_id, line, rel_type
        FROM symbol_relations
        WHERE from_symbol = ?
    """
    if path:
        sql += " AND from_path = ?"
        params.append(path)
    sql += " ORDER BY to_path, line"
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        rows = []
    neighbors = [dict(r) for r in rows]
    if not neighbors and name:
        neighbors = _heuristic_callees(db, name, path, symbol_id)
        if neighbors:
            _HEUR_CACHE["down"] = True
    neighbors, enriched = _enrich_neighbors(db, neighbors, "down")
    _REL_DENSITY["down"] += len(neighbors)
    if enriched:
        _ENRICH_CACHE["down"] = True
    return _apply_plugin("down", neighbors, {"name": name, "path": path, "symbol_id": symbol_id})


def _build_tree(
    db: Any,
    name: str,
    path: Optional[str],
    symbol_id: Optional[str],
    depth: int,
    direction: str,
    visited: Set[Tuple[str, str, str]],
    allow: Optional[Callable[[str], bool]] = None,
) -> Dict[str, Any]:
    node = {"name": name, "path": path or "", "symbol_id": symbol_id or "", "children": []}
    if depth <= 0:
        return node
    key = (direction, symbol_id or name, path or "")
    if key in visited:
        return node
    visited.add(key)
    if direction == "up":
        neighbors = _callers_for(db, name, path, symbol_id)
        for n in neighbors:
            child_path = n.get("from_path") or ""
            if allow and not allow(child_path):
                continue
            child = _build_tree(
                db,
                n.get("from_symbol") or "",
                child_path,
                n.get("from_symbol_id") or "",
                depth - 1,
                direction,
                visited,
                allow,
            )
            child["line"] = int(n.get("line") or 0)
            child["rel_type"] = n.get("rel_type") or ""
            node["children"].append(child)
    else:
        neighbors = _callees_for(db, name, path, symbol_id)
        for n in neighbors:
            child_path = n.get("to_path") or ""
            if allow and not allow(child_path):
                continue
            child = _build_tree(
                db,
                n.get("to_symbol") or "",
                child_path,
                n.get("to_symbol_id") or "",
                depth - 1,
                direction,
                visited,
                allow,
            )
            child["line"] = int(n.get("line") or 0)
            child["rel_type"] = n.get("rel_type") or ""
            node["children"].append(child)
    return node


def build_call_graph(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    name = str(args.get("symbol") or args.get("name") or "").strip()
    symbol_id = str(args.get("symbol_id") or args.get("sid") or "").strip() or None
    path = str(args.get("path") or "").strip() or None
    depth = int(args.get("depth") or 2)
    include_paths = _parse_list(args.get("include_path") or args.get("include_paths") or [])
    exclude_paths = _parse_list(args.get("exclude_path") or args.get("exclude_paths") or [])
    if not name and not symbol_id:
        raise ValueError("symbol is required")

    root_ids = resolve_root_ids(roots)
    _ACTIVE_ROOT_IDS.clear()
    _ACTIVE_ROOT_IDS.extend(root_ids)
    _ENRICH_CACHE["up"] = False
    _ENRICH_CACHE["down"] = False
    _HEUR_CACHE["up"] = False
    _HEUR_CACHE["down"] = False
    _REL_DENSITY["up"] = 0
    _REL_DENSITY["down"] = 0
    # Disambiguate if multiple symbols
    matches = _resolve_symbol(db, name, path, symbol_id)
    if not matches:
        return {"symbol": name or "", "symbol_id": symbol_id or "", "path": path or "", "matches": [], "upstream": {}, "downstream": {}}
    if not path and not symbol_id and len(matches) > 1:
        return {"symbol": name or "", "symbol_id": "", "path": "", "matches": matches, "upstream": {}, "downstream": {}}

    target = matches[0]
    t_name = target["name"]
    t_path = target["path"]
    t_sid = target.get("symbol_id") or ""
    # Enforce root scope if applicable
    if root_ids and t_path.split("/", 1)[0] not in root_ids:
        return {"symbol": name or "", "symbol_id": t_sid, "path": t_path, "matches": [], "upstream": {}, "downstream": {}}

    def _allow(p: str) -> bool:
        if not p:
            return True
        if include_paths:
            if not any(p.startswith(x) or x in p for x in include_paths):
                return False
        if exclude_paths:
            if any(p.startswith(x) or x in p for x in exclude_paths):
                return False
        return True

    upstream = _build_tree(db, t_name, t_path, t_sid, depth, "up", set(), _allow)
    downstream = _build_tree(db, t_name, t_path, t_sid, depth, "down", set(), _allow)
    payload = {
        "symbol": t_name,
        "symbol_id": t_sid,
        "path": t_path,
        "filters": {"include": include_paths, "exclude": exclude_paths},
        "matches": [target],
        "upstream": upstream,
        "downstream": downstream,
    }
    errs = _get_plugin_errors()
    if errs:
        payload["plugin_warnings"] = errs
    if _HEUR_CACHE.get("up") or _HEUR_CACHE.get("down"):
        payload["heuristic_warnings"] = [
            "symbol_relations sparse; fallback graph edges were inferred from source text"
        ]
    sort_by = str(args.get("sort") or args.get("sort_by") or "line").strip().lower()
    payload["precision_hint"] = _precision_hint(t_path)
    payload["quality_score"] = _quality_score(
        t_path,
        _ENRICH_CACHE.get("up", False) or _ENRICH_CACHE.get("down", False),
        _REL_DENSITY.get("up", 0) + _REL_DENSITY.get("down", 0),
        db,
    )
    payload["summary"] = _summarize_graph(payload)
    payload["tree"] = _format_tree(payload, sort_by=sort_by, summary=payload["summary"])
    return payload


def _format_tree(payload: Dict[str, Any], sort_by: str = "line", summary: Optional[Dict[str, Any]] = None) -> str:
    def _sort_children(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if sort_by == "name":
            return sorted(children, key=lambda c: (c.get("name", ""), c.get("line", 0)))
        return sorted(children, key=lambda c: (c.get("line", 0), c.get("name", "")))

    def _emit(node: Dict[str, Any], prefix: str, lines: List[str]) -> None:
        children = _sort_children(list(node.get("children", [])))
        for i, child in enumerate(children):
            last = i == (len(children) - 1)
            branch = "└─ " if last else "├─ "
            name = child.get("name", "")
            path = child.get("path", "")
            sid = child.get("symbol_id", "")
            label = f"{name}"
            if path:
                label += f" [{path}]"
            if sid:
                label += f" (sid={sid})"
            lines.append(f"{prefix}{branch}{label}")
            _emit(child, prefix + ("   " if last else "│  "), lines)

    head = payload.get("symbol", "")
    p = payload.get("path", "")
    sid = payload.get("symbol_id", "")
    root_label = head + (f" [{p}]" if p else "") + (f" (sid={sid})" if sid else "")
    lines: List[str] = [root_label, "UPSTREAM:"]
    _emit(payload.get("upstream", {}), "", lines)
    lines.append("DOWNSTREAM:")
    _emit(payload.get("downstream", {}), "", lines)
    if summary:
        lines.append(
            "SUMMARY: "
            f"upstream_nodes={summary.get('upstream_nodes', 0)} "
            f"downstream_nodes={summary.get('downstream_nodes', 0)} "
            f"max_depth={summary.get('max_depth', 0)} "
            f"cycle_refs={summary.get('cycle_refs', 0)}"
        )
    if payload.get("precision_hint"):
        lines.append(f"PRECISION: {payload.get('precision_hint')}")
    return "\n".join(lines)


def _summarize_graph(payload: Dict[str, Any]) -> Dict[str, Any]:
    def _count(node: Dict[str, Any], depth: int = 0, seen: Optional[Set[str]] = None) -> Tuple[int, int, int]:
        children = node.get("children", [])
        total = 0
        max_depth = depth
        cycles = 0
        if seen is None:
            seen = set()
        for c in children:
            sid = c.get("symbol_id") or f"{c.get('path','')}#{c.get('name','')}"
            if sid in seen:
                cycles += 1
                continue
            seen.add(sid)
            total += 1
            sub_count, sub_depth, sub_cycles = _count(c, depth + 1, seen)
            total += sub_count
            cycles += sub_cycles
            max_depth = max(max_depth, sub_depth)
        return total, max_depth, cycles

    up = payload.get("upstream", {}) or {}
    down = payload.get("downstream", {}) or {}
    up_count, up_depth, up_cycles = _count(up, 0, set())
    down_count, down_depth, down_cycles = _count(down, 0, set())
    return {
        "upstream_nodes": up_count,
        "downstream_nodes": down_count,
        "max_depth": max(up_depth, down_depth),
        "cycle_refs": up_cycles + down_cycles,
        "precision_hint": payload.get("precision_hint", ""),
        "quality_score": payload.get("quality_score", 0),
    }


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


def _quality_score(path: str, enriched: bool, rel_count: int, db: Any) -> int:
    hint = _precision_hint(path)
    base = 50
    if hint.startswith("high"):
        base = 85
    elif hint.startswith("low"):
        base = 30
    elif hint.startswith("medium"):
        base = 60
    # Adjust by relation density
    if rel_count >= 20:
        base = min(100, base + 5)
    elif rel_count <= 2:
        base = max(0, base - 5)
    # Adjust by file size (larger files are noisier in regex paths)
    try:
        if path:
            conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
            row = conn.execute("SELECT size FROM files WHERE path = ? LIMIT 1", (path,)).fetchone()
            if row:
                size = int(row["size"] or 0)
                if size > 200_000:
                    base = max(0, base - 10)
                elif size < 5_000:
                    base = min(100, base + 5)
    except Exception:
        pass
    if enriched:
        base = min(100, base + 10)
    return base


def execute_call_graph(args: Dict[str, Any], db: Any, logger: Any = None, roots: List[str] = None) -> Dict[str, Any]:
    if roots is None and isinstance(logger, list):
        roots = logger
        logger = None
    roots = roots or []
    def build_pack(payload: Dict[str, Any]) -> str:
        header = pack_header(
            "call_graph",
            {
                "symbol": pack_encode_text(payload.get("symbol", "")),
                "sid": pack_encode_id(payload.get("symbol_id", "")),
                "depth": str(int(args.get("depth") or 2)),
            },
            returned=1,
        )
        lines = [header]
        # Emit simple flattened nodes
        def _emit(node: Dict[str, Any], direction: str, depth: int) -> None:
            for child in node.get("children", []):
                kv = {
                    "dir": direction,
                    "depth": str(depth),
                    "name": pack_encode_id(child.get("name", "")),
                    "path": pack_encode_id(child.get("path", "")),
                    "sid": pack_encode_id(child.get("symbol_id", "")),
                    "line": str(child.get("line", 0)),
                    "rel": pack_encode_id(child.get("rel_type", "")),
                }
                lines.append(pack_line("n", kv))
                _emit(child, direction, depth + 1)
        _emit(payload.get("upstream", {}), "up", 1)
        _emit(payload.get("downstream", {}), "down", 1)
        if payload.get("tree"):
            lines.append(pack_line("t", single_value=pack_encode_text(payload.get("tree", ""))))
        if payload.get("summary"):
            lines.append(pack_line("m", {"summary": pack_encode_text(json.dumps(payload.get("summary", {})))}))
        if payload.get("precision_hint"):
            lines.append(pack_line("m", {"precision": pack_encode_text(payload.get("precision_hint", ""))}))
        if payload.get("quality_score") is not None:
            lines.append(pack_line("m", {"quality_score": str(payload.get("quality_score", 0))}))
        if payload.get("plugin_warnings"):
            lines.append(pack_line("m", {"plugin_warnings": pack_encode_text(json.dumps(payload.get("plugin_warnings", [])))}))
        if payload.get("heuristic_warnings"):
            lines.append(pack_line("m", {"heuristic_warnings": pack_encode_text(json.dumps(payload.get("heuristic_warnings", [])))}))
        return "\n".join(lines)

    try:
        payload = build_call_graph(args, db, roots)
    except ValueError as e:
        return mcp_response(
            "call_graph",
            lambda: pack_error("call_graph", ErrorCode.INVALID_ARGS, str(e)),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": str(e)}, "isError": True},
        )

    return mcp_response(
        "call_graph",
        lambda: build_pack(payload),
        lambda: payload,
    )


def _parse_list(val: Any) -> List[str]:
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    s = str(val or "").strip()
    if not s:
        return []
    if "," in s:
        return [p.strip() for p in s.split(",") if p.strip()]
    return [s]


_PLUGIN_CACHE: Dict[str, Any] = {"key": None, "mods": [], "errors": []}
PLUGIN_API_VERSION = 1


def _manifest_signature(path: str) -> str:
    if not path:
        return ""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"{p}:missing"
        stat = p.stat()
        return f"{p}:{int(stat.st_mtime)}:{int(stat.st_size)}"
    except Exception:
        return f"{path}:error"


def _load_manifest_plugins() -> List[str]:
    manifest = os.environ.get("SARI_CALLGRAPH_PLUGIN_MANIFEST", "").strip()
    if not manifest:
        return []
    strict = os.environ.get("SARI_CALLGRAPH_PLUGIN_MANIFEST_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}
    try:
        path = Path(manifest).expanduser().resolve()
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            plugins = [str(m).strip() for m in data if str(m).strip()]
            return plugins
        if isinstance(data, dict):
            items = data.get("plugins") or data.get("modules") or []
            if isinstance(items, list):
                return [str(m).strip() for m in items if str(m).strip()]
        return [] if strict else []
    except Exception:
        return [] if strict else []


def _load_plugins() -> List[Any]:
    mod_path = os.environ.get("SARI_CALLGRAPH_PLUGIN", "").strip()
    manifest = os.environ.get("SARI_CALLGRAPH_PLUGIN_MANIFEST", "").strip()
    cache_key = f"{mod_path}|{_manifest_signature(manifest)}"
    if _PLUGIN_CACHE.get("key") == cache_key:
        return list(_PLUGIN_CACHE.get("mods") or [])
    mods: List[str] = []
    if mod_path:
        mods.extend([m.strip() for m in mod_path.split(",") if m.strip()])
    mods.extend(_load_manifest_plugins())
    mods = [m for m in mods if m]
    if not mods:
        _PLUGIN_CACHE["key"] = cache_key
        _PLUGIN_CACHE["mods"] = []
        return []
    out = []
    errors = []
    for m in mods:
        try:
            out.append(importlib.import_module(m))
        except Exception:
            errors.append(m)
            continue
    _PLUGIN_CACHE["key"] = cache_key
    _PLUGIN_CACHE["mods"] = out
    _PLUGIN_CACHE["errors"] = errors
    return list(out)


def _get_plugin_errors() -> List[str]:
    return list(_PLUGIN_CACHE.get("errors") or [])


def _apply_plugin(direction: str, neighbors: List[Dict[str, Any]], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    plugins = _load_plugins()
    if not plugins:
        return neighbors
    for plugin in plugins:
        try:
            if hasattr(plugin, "augment_neighbors"):
                neighbors = plugin.augment_neighbors(direction, neighbors, context)  # type: ignore
            if hasattr(plugin, "filter_neighbors"):
                neighbors = plugin.filter_neighbors(direction, neighbors, context)  # type: ignore
        except Exception:
            logger = os.environ.get("SARI_CALLGRAPH_PLUGIN_LOG", "").strip()
            if logger:
                try:
                    with open(logger, "a", encoding="utf-8") as f:
                        f.write("callgraph plugin error\\n")
                except Exception:
                    pass
            continue
    return neighbors


_SYMBOL_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
_ENRICH_CACHE: Dict[str, bool] = {"up": False, "down": False}
_HEUR_CACHE: Dict[str, bool] = {"up": False, "down": False}
_REL_DENSITY: Dict[str, int] = {"up": 0, "down": 0}
_ACTIVE_ROOT_IDS: List[str] = []


def _coerce_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return str(content)


def _find_first_call_line(content: str, symbol_name: str) -> int:
    if not content or not symbol_name:
        return 0
    pat = re.compile(rf"\b{re.escape(symbol_name)}\s*\(")
    m = pat.search(content)
    if not m:
        return 0
    return content.count("\n", 0, m.start()) + 1


def _in_scope_path(path: str) -> bool:
    if not _ACTIVE_ROOT_IDS:
        return True
    return any(path.startswith(f"{rid}/") for rid in _ACTIVE_ROOT_IDS)


def _heuristic_callers(db: Any, name: str, path: Optional[str], symbol_id: Optional[str]) -> List[Dict[str, Any]]:
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    params: List[Any] = [f"%{name}(%"]
    sql = "SELECT path, content FROM files WHERE content LIKE ?"
    if _ACTIVE_ROOT_IDS:
        sql += " AND (" + " OR ".join(["path LIKE ?"] * len(_ACTIVE_ROOT_IDS)) + ")"
        params.extend([f"{rid}/%" for rid in _ACTIVE_ROOT_IDS])
    sql += " LIMIT 200"
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        rows = []
    target_path = path or ""
    out: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, int]] = set()
    for r in rows:
        from_path = r["path"] if hasattr(r, "__getitem__") else ""
        if not from_path or not _in_scope_path(from_path):
            continue
        text = _coerce_text(r["content"] if hasattr(r, "__getitem__") else "")
        line = _find_first_call_line(text, name)
        if line <= 0:
            continue
        try:
            sym = conn.execute(
                "SELECT name, symbol_id FROM symbols WHERE path = ? AND line <= ? AND end_line >= ? "
                "ORDER BY (end_line - line) ASC LIMIT 1",
                (from_path, line, line),
            ).fetchone()
        except Exception:
            sym = None
        if not sym:
            try:
                sym = conn.execute(
                    "SELECT name, symbol_id FROM symbols WHERE path = ? ORDER BY line LIMIT 1",
                    (from_path,),
                ).fetchone()
            except Exception:
                sym = None
        from_symbol = (sym["name"] if sym else "__file__") if hasattr(sym, "__getitem__") or sym is None else "__file__"
        from_sid = (sym["symbol_id"] if sym else "") if hasattr(sym, "__getitem__") or sym is None else ""
        if target_path and from_path == target_path and from_symbol == name:
            continue
        key = (from_path, from_symbol, line)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "from_path": from_path,
                "from_symbol": from_symbol,
                "from_symbol_id": from_sid,
                "line": line,
                "rel_type": "calls_heuristic",
            }
        )
    return out


def _heuristic_callees(db: Any, name: str, path: Optional[str], symbol_id: Optional[str]) -> List[Dict[str, Any]]:
    conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
    target = None
    if symbol_id:
        try:
            target = conn.execute(
                "SELECT path, name, line, end_line, symbol_id FROM symbols WHERE symbol_id = ? LIMIT 1",
                (symbol_id,),
            ).fetchone()
        except Exception:
            target = None
    if not target and path:
        try:
            target = conn.execute(
                "SELECT path, name, line, end_line, symbol_id FROM symbols WHERE name = ? AND path = ? ORDER BY line LIMIT 1",
                (name, path),
            ).fetchone()
        except Exception:
            target = None
    if not target:
        return []
    from_path = target["path"]
    if not from_path or not _in_scope_path(from_path):
        return []
    content = _coerce_text(db.read_file(from_path) if hasattr(db, "read_file") else "")
    if not content:
        return []
    start_line = int(target["line"] or 1)
    end_line = int(target["end_line"] or start_line)
    lines = content.splitlines()
    if start_line > len(lines):
        return []
    block = "\n".join(lines[start_line - 1 : min(end_line, len(lines))])
    call_pat = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    keywords = {
        "if", "for", "while", "switch", "catch", "return", "new", "class", "interface",
        "enum", "case", "do", "else", "try", "throw", "throws", "super", "this",
    }
    seen: Set[Tuple[str, int]] = set()
    out: List[Dict[str, Any]] = []
    for m in call_pat.finditer(block):
        callee = m.group(1)
        if callee in keywords or callee == name:
            continue
        rel_line = start_line + block.count("\n", 0, m.start())
        key = (callee, rel_line)
        if key in seen:
            continue
        seen.add(key)
        scope = from_path.rsplit("/", 1)[0] + "/" if "/" in from_path else None
        repo = from_path.split("/", 1)[0] + "/" if "/" in from_path else None
        hit = _lookup_unique_symbol(db, callee, scope, repo) or _lookup_unique_symbol(db, callee, None, repo) or _lookup_unique_symbol(db, callee)
        out.append(
            {
                "to_path": (hit or {}).get("path", ""),
                "to_symbol": callee,
                "to_symbol_id": (hit or {}).get("symbol_id", ""),
                "line": rel_line,
                "rel_type": "calls_heuristic",
            }
        )
    return out


def _lookup_unique_symbol(db: Any, name: str, scope_prefix: Optional[str] = None, repo_prefix: Optional[str] = None) -> Optional[Dict[str, Any]]:
    key = f"{scope_prefix or ''}:{repo_prefix or ''}:{name}"
    if key in _SYMBOL_CACHE:
        return _SYMBOL_CACHE[key]
    try:
        conn = db.get_read_connection() if hasattr(db, "get_read_connection") else db._read
        if scope_prefix:
            rows = conn.execute(
                "SELECT path, name, symbol_id FROM symbols WHERE name = ? AND path LIKE ? LIMIT 5",
                (name, f"{scope_prefix}%"),
            ).fetchall()
        elif repo_prefix:
            rows = conn.execute(
                "SELECT path, name, symbol_id FROM symbols WHERE name = ? AND path LIKE ? LIMIT 5",
                (name, f"{repo_prefix}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT path, name, symbol_id FROM symbols WHERE name = ? LIMIT 5",
                (name,),
            ).fetchall()
        rows = [dict(r) for r in rows]
        if len(rows) == 1:
            _SYMBOL_CACHE[key] = rows[0]
            return rows[0]
        _SYMBOL_CACHE[key] = None
        return None
    except Exception:
        _SYMBOL_CACHE[key] = None
        return None


def _enrich_neighbors(db: Any, neighbors: List[Dict[str, Any]], direction: str) -> List[Dict[str, Any]]:
    enriched_any = False
    for n in neighbors:
        if direction == "down":
            if not n.get("to_symbol_id"):
                name = n.get("to_symbol") or ""
                if name:
                    scope = None
                    from_path = n.get("from_path") or ""
                    if from_path:
                        scope = from_path.rsplit("/", 1)[0] + "/"
                    repo = from_path.split("/", 1)[0] + "/" if "/" in from_path else None
                    hit = _lookup_unique_symbol(db, name, scope, repo)
                    if not hit:
                        hit = _lookup_unique_symbol(db, name, None, repo)
                    if not hit:
                        hit = _lookup_unique_symbol(db, name)
                    if hit:
                        enriched_any = True
                        n["to_symbol_id"] = hit.get("symbol_id", "")
                        if not n.get("to_path"):
                            n["to_path"] = hit.get("path", "")
        else:
            if not n.get("from_symbol_id"):
                name = n.get("from_symbol") or ""
                if name:
                    scope = None
                    to_path = n.get("to_path") or ""
                    if to_path:
                        scope = to_path.rsplit("/", 1)[0] + "/"
                    repo = to_path.split("/", 1)[0] + "/" if "/" in to_path else None
                    hit = _lookup_unique_symbol(db, name, scope, repo)
                    if not hit:
                        hit = _lookup_unique_symbol(db, name, None, repo)
                    if not hit:
                        hit = _lookup_unique_symbol(db, name)
                    if hit:
                        enriched_any = True
                        n["from_symbol_id"] = hit.get("symbol_id", "")
                        if not n.get("from_path"):
                            n["from_path"] = hit.get("path", "")
    return neighbors, enriched_any
