import concurrent.futures
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.core.watcher import FileWatcher
from sari.core.queue_pipeline import FsEvent, FsEventKind
from sari.core.workspace import WorkspaceManager
from sari.core.settings import settings
from sari.core.scheduler.coordinator import SchedulingCoordinator
from sari.core.events import EventBus

from sari.core.db.storage import GlobalStorageManager
from .db_writer import DbTask
from .scanner import Scanner
from .worker import IndexWorker

@dataclass
class IndexStatus:
    index_ready: bool = False
    scanned_files: int = 0
    indexed_files: int = 0
    last_scan_ts: int = 0
    errors: int = 0

class Indexer:
    def __init__(self, cfg: Config, db: LocalSearchDB, logger=None, settings_obj=None):
        self.cfg, self.db, self.logger = cfg, db, logger
        self.settings = settings_obj or settings
        self.status = IndexStatus()
        self._stop = threading.Event()
        self.event_bus = EventBus()
        
        # L1 Buffer: {root_id -> [(files_row, engine_doc)]}
        self._l1_buffer: Dict[str, List[tuple]] = {}
        self._l1_docs: Dict[str, List[dict]] = {}
        self._l1_syms: Dict[str, List[tuple]] = {} # New: Buffer for symbols to ensure FK order
        self._l1_lock = threading.Lock()
        self._l1_max_size = self.settings.get_int("INDEX_L1_BATCH_SIZE", 10)

        # Phase 2 & 3: Scheduler and Workers
        self.coordinator = SchedulingCoordinator()
        self.max_workers = self.settings.INDEX_WORKERS
        self.index_mem_mb = self.settings.INDEX_MEM_MB
        if self.index_mem_mb > 0:
            worker_cap = max(1, self.index_mem_mb // 512)
            self.max_workers = min(self.max_workers, worker_cap)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        
        self.scanner = Scanner(cfg)
        self.worker = IndexWorker(cfg, db, logger, self._extract_symbols_wrapper, settings_obj=self.settings)
        
        # Global Storage Manager (L2/L3 Aggregator)
        self.storage = GlobalStorageManager.get_instance(db)
        self.watcher = None
        self._active_roots = []

    def _extract_symbols_wrapper(self, path, content):
        from sari.core.parsers.factory import ParserFactory
        parser = ParserFactory.get_parser(Path(path).suffix)
        return parser.extract(path, content) if parser else ([], [])

    def run_forever(self):
        for _ in range(self.max_workers):
            threading.Thread(target=self._worker_loop, daemon=True).start()
        
        roots = [str(Path(r).absolute()) for r in self.cfg.workspace_roots if Path(r).exists()]
        for r in roots:
            try:
                root_id = WorkspaceManager.root_id(r)
                self.db.upsert_root(root_id, r, str(Path(r).resolve()), label=Path(r).name)
            except Exception:
                pass
        self.event_bus.subscribe("fs_event", self._enqueue_fsevent)
        self.watcher = FileWatcher(roots, self._enqueue_fsevent, event_bus=self.event_bus)
        self.watcher.start()

        self.scan_once()
        self.status.index_ready = True
        
        loop_count = 0
        while not self._stop.is_set():
            time.sleep(1)
            loop_count += 1
            if loop_count % 30 == 0: # Every 30 seconds
                self._retry_failed_tasks()

    def _retry_failed_tasks(self):
        try:
            tasks = self.db.get_failed_tasks(limit=20)
            if not tasks: return
            
            roots_map = {r["root_id"]: r["real_path"] for r in self.db.get_roots()}
            
            for t in tasks:
                 db_path = t.get("path", "")
                 root_id = t.get("root_id", "")
                 if db_path and root_id and root_id in roots_map:
                     try:
                         # db_path is "root_id/rel/path"
                         rel_path = db_path.split("/", 1)[1] if "/" in db_path else ""
                         if not rel_path: continue
                         
                         full_path = Path(roots_map[root_id]) / rel_path
                         if full_path.exists():
                             st = full_path.stat()
                             self.coordinator.enqueue_priority(root_id, {
                                "kind": "scan_file", "root": Path(roots_map[root_id]), "path": full_path, 
                                "st": st, "scan_ts": int(time.time()), "excluded": False
                            }, base_priority=100.0) # High priority for retries
                             
                             if self.logger: self.logger.info(f"Retrying failed task: {rel_path}")
                     except Exception:
                         pass
        except Exception as e:
            if self.logger: self.logger.warning(f"Retry loop failed: {e}")

    def scan_once(self):
        """Phase 2: Use Fair Queue for initial scanning."""
        now, scan_ts = time.time(), int(time.time())
        self.status.last_scan_ts = scan_ts
        self.status.scanned_files = 0
        self.status.indexed_files = 0
        self._active_roots = []
        
        for root_path in self.cfg.workspace_roots:
            root = Path(root_path).absolute()
            if not root.exists(): continue
            root_id = WorkspaceManager.root_id(str(root))
            self._active_roots.append(root_id)
            
            for p, st, excluded in self.scanner.iter_file_entries(root):
                self.status.scanned_files += 1
                self.coordinator.enqueue_fair(root_id, {
                    "kind": "scan_file", "root": root, "path": p, "st": st, "scan_ts": scan_ts, "excluded": excluded
                }, base_priority=10.0)

    def _worker_loop(self):
        """Phase 2 & 3: Unified worker loop with Backpressure & Pruning."""
        while not self._stop.is_set():
            # 1. Backpressure 체크
            load = self.storage.get_queue_load()
            if load > 0.8: time.sleep(0.5)
            elif load > 0.5: time.sleep(0.1)

            # 2. Apply Read-Priority
            penalty = self.coordinator.get_sleep_penalty()
            if penalty > 0: time.sleep(penalty)

            item = self.coordinator.get_next_task()
            if not item:
                # 3. Pruning: 스캔 완료 후 큐가 비었을 때 수행
                if self.status.index_ready and self._active_roots:
                    roots_to_prune = []
                    with self._l1_lock: # Using existing lock for convenience
                        roots_to_prune = list(self._active_roots)
                        self._active_roots = []
                    
                    for rid in roots_to_prune:
                        count = self.db.prune_old_files(rid, self.status.last_scan_ts)
                        if count > 0 and self.logger:
                            self.logger.info(f"Pruned {count} dead files for {rid}")
                
                time.sleep(0.2)
                continue

            root_id, task = item
            try:
                self._handle_task(root_id, task)
            except Exception as e:
                if self.logger: self.logger.log_error(f"Task failed: {e}")

    def _handle_task(self, root_id: str, task: Dict[str, Any]):
        if task["kind"] == "scan_file":
            res = self.worker.process_file_task(task["root"], task["path"], task["st"], task["scan_ts"], time.time(), task["excluded"], root_id=root_id, force=task.get("force", False))
            if not res:
                try:
                    self.event_bus.publish("file_error", {"path": str(task.get("path", "")), "root_id": root_id})
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Event publish failed (file_error): {e}")
                return
            
            if res["type"] == "unchanged":
                self.storage.enqueue_task(DbTask(kind="update_last_seen", paths=[res["rel"]]))
                try:
                    self.event_bus.publish("file_unchanged", {"path": res["rel"], "root_id": root_id})
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Event publish failed (file_unchanged): {e}")
                return # BUG FIX: return here so unchanged files are not counted as indexed
            
            # Case: File Changed or New
            rel_path = str(task["path"].relative_to(task["root"]))
            files_row = (
                res["rel"], rel_path, root_id, res["repo"], res["mtime"], res["size"], 
                res["content"], res.get("content_hash", ""), res.get("fts_content", ""), int(time.time()), 0, 
                res["parse_status"], res["parse_reason"], res["ast_status"], res["ast_reason"], 
                res["is_binary"], res["is_minified"], 0, res.get("content_bytes", len(res["content"])), res.get("metadata_json", "{}")
            )

            with self._l1_lock:
                if root_id in self._l1_buffer:
                    self._l1_buffer[root_id] = [r for r in self._l1_buffer[root_id] if r[0] != files_row[0]]
                    self._l1_docs[root_id] = [d for d in self._l1_docs[root_id] if d.get("doc_id") != files_row[0]]
                    self._l1_syms[root_id] = [s for s in self._l1_syms.get(root_id, []) if s[1] != files_row[0]]

                self._l1_buffer.setdefault(root_id, []).append(files_row)
                doc = res.get("engine_doc")
                if doc:
                    self._l1_docs.setdefault(root_id, []).append(doc)

                if res.get("symbols"):
                    # s is (path, name, kind, line, end_line, content, parent_name, metadata, docstring, qualname, sid)
                    # Schema: (symbol_id, path, root_id, name, kind, line, end_line, content, parent_name, metadata, docstring, qualname)
                    sym_rows = [(s[10], s[0], root_id, s[1]) + s[2:10] for s in res["symbols"]]
                    self._l1_syms.setdefault(root_id, []).extend(sym_rows)

                if len(self._l1_buffer[root_id]) >= self._l1_max_size:
                    rows = self._l1_buffer.pop(root_id)
                    docs = self._l1_docs.pop(root_id, [])
                    syms = self._l1_syms.pop(root_id, [])
                    self.storage.upsert_files(rows=rows, engine_docs=docs)
                    if syms:
                        self.storage.enqueue_task(DbTask(kind="upsert_symbols", rows=syms))

            self.status.indexed_files += 1

            try:
                self.event_bus.publish("file_indexed", {"path": res["rel"], "root_id": root_id})
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Event publish failed (file_indexed): {e}")

    def _enqueue_fsevent(self, evt: FsEvent):
        root_id = WorkspaceManager.root_id(str(evt.root))
        if evt.kind in (FsEventKind.CREATED, FsEventKind.MODIFIED):
            try:
                st = Path(evt.path).stat()
                self.coordinator.enqueue_priority(root_id, {
                    "kind": "scan_file", "root": evt.root, "path": Path(evt.path), "st": st, "scan_ts": int(time.time()), "excluded": False
                }, base_priority=1.0)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to enqueue file event: {e}")
        elif evt.kind == FsEventKind.DELETED:
            db_path = f"{root_id}/{Path(evt.path).relative_to(evt.root).as_posix()}"
            with self._l1_lock:
                if root_id in self._l1_buffer:
                    self._l1_buffer[root_id] = [r for r in self._l1_buffer[root_id] if r[0] != db_path]
                    self._l1_docs[root_id] = [d for d in self._l1_docs[root_id] if d.get("doc_id") != db_path]
                    # Symbols: check if path (index 1) matches db_path
                    self._l1_syms[root_id] = [s for s in self._l1_syms.get(root_id, []) if s[1] != db_path]
            self.storage.delete_file(path=db_path, engine_deletes=[db_path])

    def stop(self):
        self._stop.set()
        if self.watcher: self.watcher.stop()
        with self._l1_lock:
            for root_id in list(self._l1_buffer.keys()):
                rows = self._l1_buffer.pop(root_id)
                docs = self._l1_docs.pop(root_id, [])
                syms = self._l1_syms.pop(root_id, [])
                if rows:
                    self.storage.upsert_files(rows=rows, engine_docs=docs)
                if syms:
                    self.storage.enqueue_task(DbTask(kind="upsert_symbols", rows=syms))
        self._executor.shutdown(wait=False)
    
    def get_queue_depths(self) -> Dict[str, int]:
        return {
            "fair_queue": self.coordinator.fair_queue.qsize(),
            "priority_queue": self.coordinator.priority_queue.qsize(),
            "db_writer": self.storage.writer.qsize()
        }

    def get_performance_metrics(self) -> Dict[str, Any]:
        return self.storage.writer.get_performance_metrics()
