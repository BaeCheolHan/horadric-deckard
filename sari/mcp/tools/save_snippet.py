import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional

from sari.mcp.tools._util import (
    mcp_response,
    pack_header,
    pack_line,
    pack_encode_id,
    pack_encode_text,
    pack_error,
    ErrorCode,
    resolve_db_path,
    resolve_fs_path,
)

from sari.core.queue_pipeline import DbTask


def _parse_path_range(path: str, start_line: Optional[int], end_line: Optional[int]) -> tuple[str, Optional[int], Optional[int]]:
    if ":" in path and (start_line is None and end_line is None):
        base, rng = path.rsplit(":", 1)
        if "-" in rng:
            a, b = rng.split("-", 1)
            try:
                return base, int(a), int(b)
            except Exception:
                return path, start_line, end_line
    return path, start_line, end_line


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


def _enqueue_or_write(db: Any, indexer: Any, row: tuple) -> None:
    writer = getattr(indexer, "_db_writer", None) if indexer else None
    if writer and DbTask:
        writer.enqueue(DbTask(kind="upsert_snippets", snippet_rows=[row]))
        return
    # Direct write (CLI or no indexer)
    prev = getattr(db, "_writer_thread_id", None)
    db.register_writer_thread(threading.get_ident())
    try:
        with db._lock:
            cur = db._write.cursor()
            # cur.execute("BEGIN")  <-- Removed
            db.upsert_snippet_tx(cur, [row])
            db._write.commit()
    finally:
        db.register_writer_thread(prev)


def build_save_snippet(args: Dict[str, Any], db: Any, roots: List[str], indexer: Any = None) -> Dict[str, Any]:
    path = str(args.get("path") or "").strip()
    tag = str(args.get("tag") or "").strip()
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    note = str(args.get("note") or "").strip()
    commit_hash = str(args.get("commit") or "").strip()
    if not path or not tag:
        raise ValueError("path and tag are required")

    path, start_line, end_line = _parse_path_range(path, start_line, end_line)
    db_path = resolve_db_path(path, roots)
    if not db_path:
        raise ValueError("path is out of workspace scope")

    if start_line is None or end_line is None:
        raise ValueError("start_line and end_line are required")

    lines = _read_lines(db, db_path, roots)
    start = max(1, int(start_line))
    end = max(start, int(end_line))
    snippet = "\n".join(lines[start - 1 : end])
    content_hash = hashlib.sha1(snippet.encode("utf-8")).hexdigest()
    anchor_before = lines[start - 2].strip() if start > 1 and len(lines) >= start - 1 else ""
    anchor_after = lines[end].strip() if end < len(lines) else ""

    root_id, rel = db_path.split("/", 1)
    repo = rel.split("/", 1)[0] if "/" in rel else "__root__"
    now = int(time.time())
    metadata_json = "{}"

    row = (
        tag,
        db_path,
        start,
        end,
        snippet,
        content_hash,
        anchor_before,
        anchor_after,
        repo,
        root_id,
        note,
        commit_hash,
        now,
        now,
        metadata_json,
    )
    _enqueue_or_write(db, indexer, row)

    return {
        "tag": tag,
        "path": db_path,
        "start_line": start,
        "end_line": end,
        "hash": content_hash,
        "anchor_before": anchor_before,
        "anchor_after": anchor_after,
        "note": note,
        "commit": commit_hash,
    }


def execute_save_snippet(args: Dict[str, Any], db: Any, roots: List[str], indexer: Any = None) -> Dict[str, Any]:
    try:
        payload = build_save_snippet(args, db, roots, indexer=indexer)
    except ValueError as e:
        return mcp_response(
            "save_snippet",
            lambda: pack_error("save_snippet", ErrorCode.INVALID_ARGS, str(e)),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": str(e)}, "isError": True},
        )

    def build_pack() -> str:
        lines = [pack_header("save_snippet", {"tag": pack_encode_text(payload["tag"])}, returned=1)]
        kv = {
            "tag": pack_encode_id(payload["tag"]),
            "path": pack_encode_id(payload["path"]),
            "start": str(payload["start_line"]),
            "end": str(payload["end_line"]),
            "hash": pack_encode_id(payload["hash"]),
        }
        lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "save_snippet",
        build_pack,
        lambda: payload,
    )
