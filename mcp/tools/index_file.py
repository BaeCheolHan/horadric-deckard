import time
from typing import Any, Dict

try:
    from app.queue_pipeline import FsEvent, FsEventKind
except Exception:
    FsEvent = None
    FsEventKind = None

def execute_index_file(args: Dict[str, Any], indexer: Any) -> Dict[str, Any]:
    """Force immediate re-indexing of a specific file."""
    path = args.get("path", "").strip()
    if not path:
        return {"success": False, "error": "File path is required"}

    if not indexer:
        return {"success": False, "error": "Indexer not available"}

    try:
        # Trigger watcher event logic which handles upsert/delete
        if FsEvent and FsEventKind:
            evt = FsEvent(kind=FsEventKind.MODIFIED, path=path, dest_path=None, ts=time.time())
            indexer._process_watcher_event(evt)
        else:
            indexer._process_watcher_event(path)
             
        return {
            "success": True,
            "path": path,
            "message": f"Successfully requested re-indexing for {path}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
