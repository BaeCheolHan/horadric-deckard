import json
from typing import Any, Dict, List
import difflib
import threading
import time
from pathlib import Path

from sari.mcp.tools._util import (
    mcp_response,
    pack_header,
    pack_line,
    pack_encode_id,
    pack_encode_text,
    pack_error,
    ErrorCode,
    resolve_fs_path,
)

def _read_lines(db: Any, db_path: str, roots: List[str]) -> List[str]:
    fs_path = resolve_fs_path(db_path, roots)
    if fs_path:
        try:
            with open(fs_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().splitlines()
        except Exception:
            pass
    raw = db.read_file_raw(db_path) if hasattr(db, "read_file_raw") else db.read_file(db_path)
    return (raw or "").splitlines()

def _remap_snippet(lines: List[str], stored: Dict[str, Any]) -> Dict[str, Any]:
    start = int(stored.get("start_line") or 0)
    end = int(stored.get("end_line") or 0)
    content = str(stored.get("content") or "")
    stored_lines = content.splitlines()
    if start > 0 and end >= start and end <= len(lines):
        current = "\n".join(lines[start - 1 : end])
        if current == content:
            return {"start": start, "end": end, "content": current, "remapped": False, "diff": ""}
    # Try exact content match
    if stored_lines:
        for i in range(0, len(lines) - len(stored_lines) + 1):
            if lines[i : i + len(stored_lines)] == stored_lines:
                return {
                    "start": i + 1,
                    "end": i + len(stored_lines),
                    "content": "\n".join(stored_lines),
                    "remapped": True,
                    "reason": "content_match",
                    "diff": _diff_snippet(content, "\n".join(stored_lines)),
                }
    anchor_before = (stored.get("anchor_before") or "").strip()
    anchor_after = (stored.get("anchor_after") or "").strip()
    if anchor_before:
        for i, line in enumerate(lines):
            if line.strip() == anchor_before:
                start_idx = i + 1
                if anchor_after:
                    for j in range(start_idx, len(lines)):
                        if lines[j].strip() == anchor_after:
                            return {
                                "start": start_idx + 1,
                                "end": j,
                                "content": "\n".join(lines[start_idx:j]),
                                "remapped": True,
                                "reason": "anchor_before_after",
                                "diff": _diff_snippet(content, "\n".join(lines[start_idx:j])),
                            }
                if stored_lines:
                    end_idx = min(len(lines), start_idx + len(stored_lines))
                    return {
                        "start": start_idx + 1,
                        "end": end_idx,
                        "content": "\n".join(lines[start_idx:end_idx]),
                        "remapped": True,
                        "reason": "anchor_before",
                        "diff": _diff_snippet(content, "\n".join(lines[start_idx:end_idx])),
                    }
    if anchor_after and stored_lines:
        for j, line in enumerate(lines):
            if line.strip() == anchor_after:
                start_idx = max(0, j - len(stored_lines))
                return {
                    "start": start_idx + 1,
                    "end": j,
                    "content": "\n".join(lines[start_idx:j]),
                    "remapped": True,
                    "reason": "anchor_after",
                    "diff": _diff_snippet(content, "\n".join(lines[start_idx:j])),
                }
    return {"start": start, "end": end, "content": content, "remapped": False, "reason": "no_match", "diff": ""}

def _diff_snippet(old: str, new: str, max_lines: int = 200, max_chars: int = 8000) -> str:
    if old == new:
        return ""
    diff_lines = list(
        difflib.unified_diff(
            (old or "").splitlines(),
            (new or "").splitlines(),
            fromfile="stored",
            tofile="current",
            lineterm="",
        )
    )
    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines] + ["... [diff truncated]"]
    diff_text = "\n".join(diff_lines)
    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars] + "\n... [diff truncated]"
    return diff_text

def _update_snippet_record(db: Any, row: Dict[str, Any], mapped: Dict[str, Any]) -> None:
    if not hasattr(db, "update_snippet_location_tx"):
        return
    snippet_id = int(row.get("id") or 0)
    if not snippet_id:
        return
    content = mapped.get("content", "")
    content_hash = ""
    try:
        import hashlib
        content_hash = hashlib.sha1(str(content).encode("utf-8")).hexdigest()
    except Exception:
        content_hash = ""
    start = int(mapped.get("start") or 0)
    end = int(mapped.get("end") or 0)
    # Recompute anchors from current file lines if possible
    anchors = {
        "before": "",
        "after": "",
    }
    try:
        raw = db.read_file_raw(row.get("path", "")) if hasattr(db, "read_file_raw") else db.read_file(row.get("path", ""))
        lines = (raw or "").splitlines()
        if start > 1 and len(lines) >= start - 1:
            anchors["before"] = lines[start - 2].strip()
        if end < len(lines):
            anchors["after"] = lines[end].strip()
    except Exception:
        pass
    prev = getattr(db, "_writer_thread_id", None)
    try:
        db.register_writer_thread(threading.get_ident())
        with db._lock:
            cur = db._write.cursor()
            cur.execute("BEGIN")
            db.update_snippet_location_tx(
                cur,
                snippet_id,
                start,
                end,
                content,
                content_hash,
                anchors.get("before", ""),
                anchors.get("after", ""),
                int(time.time()),
            )
            db._write.commit()
    finally:
        db.register_writer_thread(prev)

def _should_update(mapped: Dict[str, Any]) -> tuple[bool, str]:
    start = int(mapped.get("start") or 0)
    end = int(mapped.get("end") or 0)
    content = str(mapped.get("content") or "")
    if not mapped.get("remapped"):
        return False, "not_remapped"
    if start <= 0 or end < start:
        return False, "invalid_range"
    if not content.strip():
        return False, "empty_content"
    return True, ""

def _write_diff_file(diff_path: str, row: Dict[str, Any], mapped: Dict[str, Any]) -> None:
    try:
        base = diff_path
        if not base:
            tag = str(row.get("tag", "snippet"))
            base = f"~/.cache/sari/snippet-diffs/{tag}.diff"
        path = Path(base).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"# tag={row.get('tag','')} path={row.get('path','')} start={row.get('start_line','')} end={row.get('end_line','')}\n"
        diff = mapped.get("diff", "")
        path.write_text(header + (diff or "") + "\n", encoding="utf-8")
    except Exception:
        pass

def _write_snapshot_files(diff_path: str, row: Dict[str, Any], mapped: Dict[str, Any]) -> None:
    try:
        base = diff_path
        if not base:
            tag = str(row.get("tag", "snippet"))
            base = f"~/.cache/sari/snippet-diffs/{tag}.diff"
        base_path = Path(base).expanduser().resolve()
        dir_path = base_path.parent
        dir_path.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        prefix = f"{row.get('tag','snippet')}_{row.get('id','')}_{ts}"
        old_path = dir_path / f"{prefix}_stored.txt"
        new_path = dir_path / f"{prefix}_current.txt"
        old_content = str(row.get("content") or "")
        new_content = str(mapped.get("content") or "")
        old_path.write_text(old_content + "\n", encoding="utf-8")
        new_path.write_text(new_content + "\n", encoding="utf-8")
    except Exception:
        pass


def build_get_snippet(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    tag = str(args.get("tag") or "").strip()
    query = str(args.get("query") or "").strip()
    limit = int(args.get("limit") or 20)
    remap = str(args.get("remap") or "1").strip().lower() not in {"0", "false", "no", "off"}
    update = str(args.get("update") or "0").strip().lower() in {"1", "true", "yes", "on"}
    diff_path = str(args.get("diff_path") or "").strip()
    history = str(args.get("history") or "").strip().lower() in {"1", "true", "yes", "on"}
    if tag:
        rows = db.list_snippets_by_tag(tag)
        if remap:
            for r in rows:
                if r.get("path"):
                    mapped = _remap_snippet(_read_lines(db, r["path"], roots), r)
                    r["current_start_line"] = mapped["start"]
                    r["current_end_line"] = mapped["end"]
                    r["current_content"] = mapped["content"]
                    r["remapped"] = mapped.get("remapped", False)
                    r["remap_reason"] = mapped.get("reason", "")
                    r["diff"] = mapped.get("diff", "")
                    if update and r.get("id"):
                        ok, reason = _should_update(mapped)
                        if ok:
                            _update_snippet_record(db, r, mapped)
                            r["updated"] = True
                            if mapped.get("diff"):
                                _write_diff_file(diff_path, r, mapped)
                            _write_snapshot_files(diff_path, r, mapped)
                        else:
                            r["updated"] = False
                            r["update_skipped_reason"] = reason
                if history and r.get("id"):
                    r["versions"] = db.list_snippet_versions(int(r["id"]))
        return {"tag": tag, "results": rows}
    if query:
        rows = db.search_snippets(query, limit=limit)
        if remap:
            for r in rows:
                if r.get("path"):
                    mapped = _remap_snippet(_read_lines(db, r["path"], roots), r)
                    r["current_start_line"] = mapped["start"]
                    r["current_end_line"] = mapped["end"]
                    r["current_content"] = mapped["content"]
                    r["remapped"] = mapped.get("remapped", False)
                    r["remap_reason"] = mapped.get("reason", "")
                    r["diff"] = mapped.get("diff", "")
                    if update and r.get("id"):
                        ok, reason = _should_update(mapped)
                        if ok:
                            _update_snippet_record(db, r, mapped)
                            r["updated"] = True
                            if mapped.get("diff"):
                                _write_diff_file(diff_path, r, mapped)
                            _write_snapshot_files(diff_path, r, mapped)
                        else:
                            r["updated"] = False
                            r["update_skipped_reason"] = reason
                if history and r.get("id"):
                    r["versions"] = db.list_snippet_versions(int(r["id"]))
        return {"query": query, "results": rows}
    raise ValueError("tag or query is required")


def execute_get_snippet(args: Dict[str, Any], db: Any, logger: Any = None, roots: List[str] = None) -> Dict[str, Any]:
    if roots is None and isinstance(logger, list):
        roots = logger
        logger = None
    roots = roots or []
    try:
        payload = build_get_snippet(args, db, roots)
    except ValueError as e:
        return mcp_response(
            "get_snippet",
            lambda: pack_error("get_snippet", ErrorCode.INVALID_ARGS, str(e)),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": str(e)}, "isError": True},
        )

    def build_pack() -> str:
        lines = [pack_header("get_snippet", {}, returned=len(payload.get("results", [])))]
        for r in payload.get("results", []):
            kv = {
                "tag": pack_encode_id(r.get("tag", "")),
                "path": pack_encode_id(r.get("path", "")),
                "start": str(r.get("start_line", 0)),
                "end": str(r.get("end_line", 0)),
                "cur_start": str(r.get("current_start_line", 0)),
                "cur_end": str(r.get("current_end_line", 0)),
                "hash": pack_encode_id(r.get("content_hash", "")),
            }
            lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "get_snippet",
        build_pack,
        lambda: payload,
    )
