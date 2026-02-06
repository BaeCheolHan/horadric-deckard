import json
import os
import urllib.parse
from enum import Enum
from typing import Any, Dict, Optional, List, Callable, Tuple
from pathlib import Path
from sari.core.workspace import WorkspaceManager

# --- Constants & Enums ---

class ErrorCode(str, Enum):
    INVALID_ARGS = "INVALID_ARGS"
    NOT_INDEXED = "NOT_INDEXED"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    IO_ERROR = "IO_ERROR"
    DB_ERROR = "DB_ERROR"
    INTERNAL = "INTERNAL"
    ERR_INDEXER_FOLLOWER = "ERR_INDEXER_FOLLOWER"
    ERR_INDEXER_DISABLED = "ERR_INDEXER_DISABLED"
    ERR_ROOT_OUT_OF_SCOPE = "ERR_ROOT_OUT_OF_SCOPE"
    ERR_MCP_HTTP_UNSUPPORTED = "ERR_MCP_HTTP_UNSUPPORTED"
    ERR_ENGINE_NOT_INSTALLED = "ERR_ENGINE_NOT_INSTALLED"
    ERR_ENGINE_INIT = "ERR_ENGINE_INIT"
    ERR_ENGINE_QUERY = "ERR_ENGINE_QUERY"
    ERR_ENGINE_INDEX = "ERR_ENGINE_INDEX"
    ERR_ENGINE_UNAVAILABLE = "ERR_ENGINE_UNAVAILABLE"
    ERR_ENGINE_REBUILD = "ERR_ENGINE_REBUILD"

# --- Format Selection ---

# --- Format Selection ---

def _get_env_any(key_suffix: str, default: Any = None) -> Any:
    val = os.environ.get(f"SARI_{key_suffix}")
    if val is not None:
        return val
    allow_legacy = str(os.environ.get("SARI_ALLOW_LEGACY", "")).strip().lower() in {"1", "true", "yes", "on"}
    if allow_legacy:
        raw = os.environ.get(key_suffix)
        if raw is not None:
            return raw
    return default

def _get_format() -> str:
    """Get response format (pack or json).
    
    Returns 'pack' or 'json'.
    Defaults to 'pack'.
    """
    fmt = _get_env_any("FORMAT", "pack").strip().lower()
    return "json" if fmt == "json" else "pack"

def _compact_enabled() -> bool:
    """Always use compact JSON for better token efficiency."""
    return True

# --- PACK1 Encoders ---

def pack_encode_text(s: Any) -> str:
    """
    ENC_TEXT: safe=""
    Used for snippet, msg, reason, detail, hint.
    """
    return urllib.parse.quote(str(s), safe="")

def pack_encode_id(s: Any) -> str:
    """
    ENC_ID: safe="/._-:@"
    Used for path, repo, name (identifiers).
    """
    return urllib.parse.quote(str(s), safe="/._-:@")

# --- PACK1 Builders ---

def pack_header(tool: str, kv: Dict[str, Any], returned: Optional[int] = None,
                total: Optional[int] = None, total_mode: Optional[str] = None) -> str:
    """
    Builds the PACK1 header line.
    PACK1 tool=<tool> ok=true k=v ... [returned=<N>] [total=<M>] [total_mode=<mode>]
    """
    parts = ["PACK1", f"tool={tool}", "ok=true"]

    # Add custom KV pairs
    for k, v in kv.items():
        parts.append(f"{k}={v}")

    if returned is not None:
        parts.append(f"returned={returned}")

    if total_mode:
        parts.append(f"total_mode={total_mode}")

    if total is not None and total_mode != "none":
        parts.append(f"total={total}")

    return " ".join(parts)

def pack_line(kind: str, kv: Optional[Dict[str, str]] = None, single_value: Optional[str] = None) -> str:
    """
    Builds a PACK1 record line.
    If single_value is provided: <kind>:<single_value>
    If kv is provided: <kind>:k=v k2=v2 ...
    """
    if single_value is not None:
        return f"{kind}:{single_value}"

    if kv:
        field_strs = [f"{k}={v}" for k, v in kv.items()]
        return f"{kind}:{ ' '.join(field_strs) }"

    return f"{kind}:"

def pack_error(tool: str, code: Any, msg: str, hints: List[str] = None, trace: str = None, fields: Dict[str, Any] = None) -> str:
    """
    Generates PACK1 error response.
    PACK1 tool=<tool> ok=false code=<CODE> msg=<ENCODED_MSG> [hint=<ENC>] [trace=<ENC>]
    """
    parts = [
        "PACK1",
        f"tool={tool}",
        "ok=false",
        f"code={code.value if isinstance(code, ErrorCode) else str(code)}",
        f"msg={pack_encode_text(msg)}",
    ]
    if hints:
        joined = " | ".join(hints)
        parts.append(f"hint={pack_encode_text(joined)}")
    if trace:
        parts.append(f"trace={pack_encode_text(trace)}")
    if fields:
        for k, v in fields.items():
            parts.append(f"{k}={pack_encode_text(v)}")
    return " ".join(parts)

def pack_truncated(next_offset: int, limit: int, truncated_state: str) -> str:
    """
    m:truncated=true|maybe next=use_offset offset=<nextOffset> limit=<limit>
    """
    return f"m:truncated={truncated_state} next=use_offset offset={next_offset} limit={limit}"

# --- Main Utility ---

def mcp_response(
    tool_name: str,
    pack_func: Callable[[], str],
    json_func: Callable[[], Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Helper to dispatch between PACK1 and JSON based on configuration.

    pack_func: function that returns (str) - the full PACK1 text payload.
    json_func: function that returns (dict) - the dict for JSON serialization.
    """
    fmt = _get_format()

    try:
        if fmt == "pack":
            text_output = pack_func()
            return {
                "content": [{"type": "text", "text": text_output}]
            }
        else:
            # JSON mode (Legacy/Debug)
            data = json_func()

            if _compact_enabled():
                json_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            else:
                json_text = json.dumps(data, ensure_ascii=False, indent=2)

            res = {"content": [{"type": "text", "text": json_text}]}
            if isinstance(data, dict):
                res.update(data)
            return res
    except Exception as e:
        import traceback
        err_msg = str(e)
        stack = traceback.format_exc()

        if fmt == "pack":
            return {
                "content": [{"type": "text", "text": pack_error(tool_name, ErrorCode.INTERNAL, err_msg, trace=stack)}],
                "isError": True
            }
        else:
            err_obj = {
                "error": {"code": ErrorCode.INTERNAL.value, "message": err_msg, "trace": stack},
                "isError": True
            }
            return mcp_json(err_obj)


def mcp_json(obj):
    """Utility to format dictionary as standard MCP response."""
    if _compact_enabled():
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        payload = json.dumps(obj, ensure_ascii=False, indent=2)
    res = {"content": [{"type": "text", "text": payload}]}
    if isinstance(obj, dict):
        res.update(obj)
    return res


def resolve_root_ids(roots: List[str]) -> List[str]:
    if not roots or not WorkspaceManager:
        return []
    out: List[str] = []
    allow_legacy = str(os.environ.get("SARI_ALLOW_LEGACY", "")).strip().lower() in {"1", "true", "yes", "on"}
    for r in roots:
        try:
            out.append(WorkspaceManager.root_id_for_workspace(r))
            if allow_legacy:
                out.append(WorkspaceManager.root_id(r))
        except Exception:
            continue
    return list(dict.fromkeys(out))


def _intersect_preserve_order(base: List[str], rhs: List[str]) -> List[str]:
    rhs_set = set(rhs)
    return [x for x in base if x in rhs_set]


def resolve_repo_scope(
    repo: Optional[str],
    roots: List[str],
    db: Optional[Any] = None,
) -> Tuple[Optional[str], List[str]]:
    """
    Resolve repo argument into:
    - effective_repo: value for files.repo exact filter (when repo token is truly repo bucket like 'src')
    - effective_root_ids: root scope inferred from root labels/names/paths and DB metadata
    """
    allowed_root_ids = resolve_root_ids(roots)
    repo_raw = str(repo or "").strip()
    if not repo_raw:
        return None, allowed_root_ids

    q = repo_raw.lower()
    allow_legacy = str(os.environ.get("SARI_ALLOW_LEGACY", "")).strip().lower() in {"1", "true", "yes", "on"}
    matched_root_ids: List[str] = []
    for r in roots or []:
        try:
            rp = Path(r).expanduser().resolve()
            name = rp.name.lower()
            full = str(rp).lower()
            if q == name or q == full or (q and q in name):
                matched_root_ids.append(WorkspaceManager.root_id_for_workspace(str(rp)))
                if allow_legacy:
                    matched_root_ids.append(WorkspaceManager.root_id(str(rp)))
        except Exception:
            continue

    db_repo_root_ids: List[str] = []
    db_root_match_ids: List[str] = []
    if db is not None:
        conn = getattr(db, "_read", None)
        if conn is None and hasattr(db, "get_read_connection"):
            try:
                conn = db.get_read_connection()
            except Exception:
                conn = None
        if conn is not None:
            try:
                rows = conn.execute(
                    "SELECT DISTINCT root_id FROM files WHERE LOWER(COALESCE(repo, '')) = LOWER(?)",
                    (repo_raw,),
                ).fetchall()
                db_repo_root_ids = [str(r[0]) for r in rows if r and r[0]]
            except Exception:
                db_repo_root_ids = []
            try:
                rows = conn.execute(
                    "SELECT root_id FROM roots WHERE LOWER(COALESCE(label, '')) = LOWER(?) OR LOWER(COALESCE(root_path, '')) LIKE ?",
                    (repo_raw, f"%/{q}%"),
                ).fetchall()
                db_root_match_ids = [str(r[0]) for r in rows if r and r[0]]
            except Exception:
                db_root_match_ids = []

    if db_root_match_ids:
        matched_root_ids.extend(db_root_match_ids)

    if matched_root_ids:
        if allowed_root_ids:
            return None, _intersect_preserve_order(allowed_root_ids, matched_root_ids)
        return None, list(dict.fromkeys(matched_root_ids))

    if db_repo_root_ids:
        if allowed_root_ids:
            return repo_raw, _intersect_preserve_order(allowed_root_ids, db_repo_root_ids)
        return repo_raw, list(dict.fromkeys(db_repo_root_ids))

    return repo_raw, allowed_root_ids

def _is_safe_relative_path(rel: str) -> bool:
    if rel is None:
        return False
    rel = str(rel).strip()
    if not rel:
        return False
    p = Path(rel)
    if p.is_absolute():
        return False
    # Block traversal and Windows drive-like segments.
    for part in p.parts:
        if part in {"..", ""}:
            return False
        if ":" in part:
            return False
    return True


def resolve_db_path(input_path: str, roots: List[str]) -> Optional[str]:
    """
    Accepts either db-path (root-xxxx/rel) or filesystem path.
    Returns normalized db-path if allowed, else None.
    """
    if not input_path:
        return None
    if "/" in input_path and input_path.startswith("root-"):
        root_id, rel = input_path.split("/", 1)
        if not _is_safe_relative_path(rel):
            return None
        if root_id in resolve_root_ids(roots):
            return input_path
        return None
    if not WorkspaceManager:
        return None
    if input_path.startswith("root-") and "/" not in input_path:
        return None
    val = _get_env_any("FOLLOW_SYMLINKS", "0")
    follow_symlinks = (val.strip().lower() in ("1", "true", "yes", "on"))
    try:
        p = Path(os.path.expanduser(input_path))
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
    except Exception:
        return None

    for root in roots:
        try:
            root_norm = WorkspaceManager._normalize_path(root, follow_symlinks=follow_symlinks)  # type: ignore
            root_path = Path(root_norm)
            if p == root_path or root_path in p.parents:
                rel = p.relative_to(root_path).as_posix()
                return f"{WorkspaceManager.root_id_for_workspace(str(root_path))}/{rel}"
        except Exception:
            continue
    return None


def resolve_fs_path(db_path: str, roots: List[str]) -> Optional[str]:
    """
    Resolve db-path (root-xxxx/rel) to filesystem path using roots.
    Returns absolute path if in scope, else None.
    """
    if not db_path or not db_path.startswith("root-") or "/" not in db_path:
        return None
    if not WorkspaceManager:
        return None
    root_id, rel = db_path.split("/", 1)
    if not _is_safe_relative_path(rel):
        return None
    allow_legacy = str(os.environ.get("SARI_ALLOW_LEGACY", "")).strip().lower() in {"1", "true", "yes", "on"}
    for r in roots:
        try:
            rid_new = WorkspaceManager.root_id_for_workspace(r)
            rid_legacy = WorkspaceManager.root_id(r) if allow_legacy else ""
        except Exception:
            continue
        if root_id not in {rid_new, rid_legacy}:
            continue
        root_path = Path(r).expanduser().resolve()
        candidate = (root_path / rel).resolve()
        if candidate == root_path or root_path in candidate.parents:
            return str(candidate)
        return None
    return None
