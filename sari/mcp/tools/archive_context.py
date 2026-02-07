import json
import threading
import time
from datetime import datetime
from typing import Any, Dict, List

from sari.mcp.tools._util import (
    mcp_response,
    pack_header,
    pack_line,
    pack_encode_id,
    pack_encode_text,
    pack_error,
    ErrorCode,
)

from sari.core.queue_pipeline import DbTask


def _enqueue_or_write(db: Any, indexer: Any, row: tuple) -> None:
    writer = getattr(indexer, "_db_writer", None) if indexer else None
    if writer and DbTask:
        writer.enqueue(DbTask(kind="upsert_contexts", context_rows=[row]))
        return
    prev = getattr(db, "_writer_thread_id", None)
    db.register_writer_thread(threading.get_ident())
    try:
        with db._lock:
            cur = db._write.cursor()
            # cur.execute("BEGIN")  <-- Removed
            db.upsert_context_tx(cur, [row])
            db._write.commit()
    finally:
        db.register_writer_thread(prev)


def build_archive_context(args: Dict[str, Any], db: Any, indexer: Any = None) -> Dict[str, Any]:
    topic = str(args.get("topic") or "").strip()
    content = str(args.get("content") or "").strip()
    tags = args.get("tags") or []
    related = args.get("related_files") or []
    source = str(args.get("source") or "").strip()
    valid_from_raw = args.get("valid_from")
    valid_until_raw = args.get("valid_until")
    deprecated = int(bool(args.get("deprecated"))) if args.get("deprecated") is not None else 0
    if not topic or not content:
        raise ValueError("topic and content are required")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if isinstance(related, str):
        related = [r.strip() for r in related.split(",") if r.strip()]
    tags_json = json.dumps(tags, ensure_ascii=False)
    related_json = json.dumps(related, ensure_ascii=False)
    def _parse_ts(v):
        if v is None or v == "":
            return 0
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if s.isdigit():
            return int(s)
        try:
            return int(datetime.fromisoformat(s).timestamp())
        except Exception:
            return 0
    valid_from = _parse_ts(valid_from_raw)
    valid_until = _parse_ts(valid_until_raw)
    now = int(time.time())
    row = (topic, content, tags_json, related_json, source, valid_from, valid_until, deprecated, now, now)
    _enqueue_or_write(db, indexer, row)
    return {"topic": topic, "tags": tags, "related_files": related, "source": source, "valid_from": valid_from, "valid_until": valid_until, "deprecated": deprecated}


def execute_archive_context(args: Dict[str, Any], db: Any, roots: List[str], indexer: Any = None) -> Dict[str, Any]:
    try:
        payload = build_archive_context(args, db, indexer=indexer)
    except ValueError as e:
        return mcp_response(
            "archive_context",
            lambda: pack_error("archive_context", ErrorCode.INVALID_ARGS, str(e)),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": str(e)}, "isError": True},
        )

    def build_pack() -> str:
        lines = [pack_header("archive_context", {"topic": pack_encode_text(payload["topic"])}, returned=1)]
        kv = {
            "topic": pack_encode_id(payload["topic"]),
            "tags": pack_encode_text(",".join(payload.get("tags", []))),
        }
        lines.append(pack_line("r", kv))
        return "\n".join(lines)

    return mcp_response(
        "archive_context",
        build_pack,
        lambda: payload,
    )
