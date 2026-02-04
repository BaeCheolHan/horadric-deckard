import time
from typing import Any, Dict, List

try:
    from sari.core.queue_pipeline import FsEvent, FsEventKind
except Exception:
    FsEvent = None
    FsEventKind = None

from sari.mcp.tools._util import mcp_response, pack_error, ErrorCode, resolve_db_path, pack_header, pack_line, pack_encode_id

def execute_index_file(args: Dict[str, Any], indexer: Any, roots: List[str]) -> Dict[str, Any]:
    """Force immediate re-indexing of a specific file."""
    path = args.get("path", "").strip()
    if not path:
        return mcp_response(
            "index_file",
            lambda: pack_error("index_file", ErrorCode.INVALID_ARGS, "File path is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "File path is required"}, "isError": True},
        )

    if not indexer:
        return mcp_response(
            "index_file",
            lambda: pack_error("index_file", ErrorCode.INTERNAL, "Indexer not available"),
            lambda: {"error": {"code": ErrorCode.INTERNAL.value, "message": "Indexer not available"}, "isError": True},
        )

    if not getattr(indexer, "indexing_enabled", True):
        mode = getattr(indexer, "indexer_mode", "off")
        code = ErrorCode.ERR_INDEXER_DISABLED if mode == "off" else ErrorCode.ERR_INDEXER_FOLLOWER
        return mcp_response(
            "index_file",
            lambda: pack_error("index_file", code, "Indexer is not available in follower/off mode", fields={"mode": mode}),
            lambda: {"error": {"code": code.value, "message": "Indexer is not available in follower/off mode", "data": {"mode": mode}}, "isError": True},
        )

    db_path = resolve_db_path(path, roots)
    if not db_path:
        return mcp_response(
            "index_file",
            lambda: pack_error("index_file", ErrorCode.ERR_ROOT_OUT_OF_SCOPE, f"Path out of scope: {path}", hints=["outside final_roots"]),
            lambda: {"error": {"code": ErrorCode.ERR_ROOT_OUT_OF_SCOPE.value, "message": f"Path out of scope: {path}"}, "isError": True},
        )

    try:
        fs_path = path
        if hasattr(indexer, "_decode_db_path"):
            decoded = indexer._decode_db_path(db_path)  # type: ignore[attr-defined]
            if decoded:
                _, fs_path = decoded
                fs_path = str(fs_path)
        # Trigger watcher event logic which handles upsert/delete
        if FsEvent and FsEventKind:
            evt = FsEvent(kind=FsEventKind.MODIFIED, path=fs_path, dest_path=None, ts=time.time())
            indexer._process_watcher_event(evt)
        else:
            indexer._process_watcher_event(fs_path)

        def build_pack() -> str:
            lines = [pack_header("index_file", {}, returned=1)]
            lines.append(pack_line("m", {"path": pack_encode_id(db_path), "requested": "true"}))
            return "\n".join(lines)

        return mcp_response(
            "index_file",
            build_pack,
            lambda: {"success": True, "path": db_path, "message": f"Successfully requested re-indexing for {db_path}"},
        )
    except Exception as e:
        return mcp_response(
            "index_file",
            lambda: pack_error("index_file", ErrorCode.INTERNAL, str(e)),
            lambda: {"error": {"code": ErrorCode.INTERNAL.value, "message": str(e)}, "isError": True},
        )