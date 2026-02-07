import threading
import time
import logging
from collections import OrderedDict
from typing import Dict, List, Any, Optional, Tuple
from sari.core.indexer.db_writer import DBWriter, DbTask
from sari.core.settings import settings
from sari.core.utils.cleaner import clean_for_fts

logger = logging.getLogger("sari.storage")

class GlobalStorageManager:
    """
    Robust 3-Tier Storage Pipeline (L2/L3 Coordinator).
    Features: Move policy, Version Protection, Backpressure, and Partial Failure recovery.
    """
    _instance = None
    _lock = threading.Lock()
    _last_switch_block_reason = ""
    _last_switch_block_ts = 0.0

    def __init__(self, db: Any):
        self.db = db
        # DBWriter에 커밋 완료 콜백 등록
        # max_wait를 0.05초로 설정하여 실시간 반응성 극대화
        self.writer = DBWriter(db, logger=logger, max_batch=settings.get_int("DB_BATCH_SIZE", 500), max_wait=0.05, on_commit=self._on_db_commit)
        
        # L2 Memory Overlay: {path -> files_row_tuple}
        self._overlay_files = OrderedDict()
        self._overlay_lock = threading.Lock()
        self._max_overlay_size = settings.get_int("STORAGE_OVERLAY_SIZE", 1000)

    @classmethod
    def get_instance(cls, db: Any = None):
        with cls._lock:
            if cls._instance is not None and db is not None:
                current_db = getattr(cls._instance, "db", None)
                current_path = getattr(current_db, "db_path", None)
                next_path = getattr(db, "db_path", None)
                if current_db is not db and current_path != next_path:
                    shutdown_ok = False
                    try:
                        shutdown_ok = cls._instance.shutdown()
                    except Exception:
                        shutdown_ok = False
                    if shutdown_ok:
                        cls._last_switch_block_reason = ""
                        cls._last_switch_block_ts = 0.0
                        cls._instance = None
                    else:
                        cls._last_switch_block_reason = "previous writer did not stop cleanly"
                        cls._last_switch_block_ts = time.time()
                        logger.warning("Skip storage instance switch: previous writer did not stop cleanly.")
            if cls._instance is None:
                if db is None:
                    from sari.core.workspace import WorkspaceManager
                    from sari.core.db.main import LocalSearchDB
                    db = LocalSearchDB(str(WorkspaceManager.get_global_db_path()))
                cls._instance = cls(db)
                cls._instance.start()
                cls._last_switch_block_reason = ""
                cls._last_switch_block_ts = 0.0
            return cls._instance

    def start(self):
        self.writer.start()

    def stop(self):
        return self.writer.stop()

    def _on_db_commit(self, paths: List[str]):
        """L2 -> L3 이동 완료 시 L2 데이터 삭제 (Eviction)"""
        with self._overlay_lock:
            for path in paths:
                self._overlay_files.pop(path, None)

    def upsert_files(self, rows: List[tuple], engine_docs: Optional[List[dict]] = None):
        """L1 -> L2 Handover with Normalization and Version Check (SQLite & Tantivy Sync)."""
        cleaned_rows = []
        valid_doc_ids = set()
        
        with self._overlay_lock:
            for row in rows:
                path, mtime = row[0], row[4]
                
                existing = self._overlay_files.get(path)
                if existing and existing[4] > mtime:
                    continue

                r_list = list(row)
                if len(r_list) > 8:
                    r_list[8] = clean_for_fts(r_list[8])
                new_row = tuple(r_list)
                
                cleaned_rows.append(new_row)
                valid_doc_ids.add(path)
                self._overlay_files[path] = new_row
                self._overlay_files.move_to_end(path)
                if len(self._overlay_files) > self._max_overlay_size:
                    self._overlay_files.popitem(last=False)
        
        if cleaned_rows:
            # engine_docs도 필터링된 항목만 포함
            filtered_docs = [d for d in (engine_docs or []) if d.get("id") in valid_doc_ids]
            self.writer.enqueue(DbTask(kind="upsert_files", rows=cleaned_rows, engine_docs=filtered_docs))

    def delete_file(self, path: str, engine_deletes: Optional[List[str]] = None):
        """L2 캐시에서 즉시 제거하고 L3 삭제 큐에 삽입."""
        with self._overlay_lock:
            self._overlay_files.pop(path, None)
        
        self.writer.enqueue(DbTask(kind="delete_path", path=path, engine_deletes=engine_deletes))

    def enqueue_task(self, task: DbTask):
        """General task handover."""
        self.writer.enqueue(task)

    def get_queue_load(self) -> float:
        """쓰기 큐 부하 측정 (0.0 ~ 1.0)."""
        qsize = self.writer.qsize()
        return min(1.0, qsize / 5000.0)

    def get_recent_files(self, query: str, root_id: Optional[str] = None, limit: int = 10) -> List[tuple]:
        """Query the L2 memory overlay."""
        results = []
        q = (query or "").lower()
        with self._overlay_lock:
            for path, row in reversed(list(self._overlay_files.items())):
                if len(results) >= limit:
                    break
                if root_id and row[2] != root_id:
                    continue
                content_match = False
                if len(row) > 8:
                    fts_content = row[8]
                    if fts_content and q in str(fts_content).lower():
                        content_match = True
                if q in str(path).lower() or content_match:
                    # Normalize to match SearchEngine's SQLite query structure:
                    # (path, root_id, repo, mtime, size, content)
                    # row structure from Indexer:
                    # 0: path, 1: rel_path, 2: root_id, 3: repo, 4: mtime, 5: size, 6: content, ...
                    normalized = (row[0], row[2], row[3], row[4], row[5], row[6])
                    results.append(normalized)
        return results

    def shutdown(self) -> bool:
        flushed = self.writer.flush()
        stopped = self.stop()
        if not (flushed and stopped):
            logger.warning("Storage shutdown incomplete (flushed=%s, stopped=%s)", flushed, stopped)
        return bool(flushed and stopped)
