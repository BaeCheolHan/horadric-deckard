import concurrent.futures
import threading
import time
import os
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
from collections import OrderedDict
from .db_writer import DbTask
from .scanner import Scanner
from .worker import IndexWorker

@dataclass
class IndexStatus:
    index_ready: bool = False
    candidates: int = 0
    scanned_files: int = 0
    indexed_files: int = 0
    indexed_new: int = 0
    indexed_updated: int = 0
    skipped_unchanged: int = 0
    last_scan_ts: int = 0
    errors: int = 0
    walk_time: float = 0.0
    read_time: float = 0.0
    parse_time: float = 0.0
    db_time: float = 0.0
    ast_ok: int = 0
    ast_failed: int = 0
    ast_skipped: int = 0
    symbols_emitted: int = 0
    relations_emitted: int = 0
    scan_started_ts: int = 0
    scan_finished_ts: int = 0
    scan_duration_ms: int = 0

class Indexer:
    def __init__(self, cfg: Config, db: LocalSearchDB, logger=None, settings_obj=None):
        self.cfg, self.db, self.logger = cfg, db, logger
        self.settings = settings_obj or settings
        self.status = IndexStatus()
        self._stop = threading.Event()
        self.event_bus = EventBus()
        
        # L1 Buffer: {root_id -> OrderedDict(path -> (files_row, engine_doc, syms, rels))}
        self._l1_buffer: Dict[str, OrderedDict] = {}
        self._l1_lock = threading.Lock()
        self._l1_max_size = self.settings.get_int("INDEX_L1_BATCH_SIZE", 500)
        self._slow_files = [] # List of (path, ms)

        # Phase 2 & 3: Scheduler and Workers
        self.coordinator = SchedulingCoordinator()
        self.max_workers = self.settings.INDEX_WORKERS
        self.index_mem_mb = self.settings.INDEX_MEM_MB
        if self.index_mem_mb > 0:
            worker_cap = max(1, self.index_mem_mb // 512)
            self.max_workers = min(self.max_workers, worker_cap)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        self._worker_threads: List[threading.Thread] = []
        
        # Get active workspaces for intelligent overlap detection
        active_ws = []
        try:
            from sari.core.server_registry import ServerRegistry
            reg = ServerRegistry()
            data = reg._load()
            active_ws = list(data.get("workspaces", {}).keys())
        except Exception:
            pass

        self.scanner = Scanner(cfg, active_workspaces=active_ws)
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
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._worker_threads.append(t)
        
        roots = [str(Path(r).absolute()) for r in self.cfg.workspace_roots if Path(r).exists()]
        for r in roots:
            try:
                root_id = WorkspaceManager.root_id_for_workspace(r)
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
        """Phase 2: Use Fair Queue for initial scanning with Staging architecture."""
        start_walk = time.time()
        now, scan_ts = time.time(), int(time.time())
        self.status.last_scan_ts = scan_ts
        self.status.scan_started_ts = scan_ts
        self.status.scan_finished_ts = 0
        self.status.scan_duration_ms = 0
        self.status.candidates = 0
        self.status.scanned_files = 0
        self.status.indexed_files = 0
        self.status.read_time = 0.0
        self.status.parse_time = 0.0
        self.status.ast_ok = 0
        self.status.ast_failed = 0
        self.status.ast_skipped = 0
        self.status.symbols_emitted = 0
        self.status.relations_emitted = 0
        self._active_roots = []
        
        # Prepare staging for bulk ingestion
        self.storage.enqueue_task(DbTask(kind="create_staging"))
        
        for root_path in self.cfg.workspace_roots:
            # ... (rest of loop)
            root = Path(root_path).absolute()
            if not root.exists(): continue
            root_id = WorkspaceManager.root_id_for_workspace(str(root))
            self._active_roots.append(root_id)
            
            for p, st, excluded in self.scanner.iter_file_entries(root):
                self.status.candidates += 1
                self.coordinator.enqueue_fair(root_id, {
                    "kind": "scan_file", "root": root, "path": p, "st": st, "scan_ts": scan_ts, "excluded": excluded,
                    "use_staging": True # Flag for worker to use staging kind
                }, base_priority=10.0)
        
        self.status.walk_time = time.time() - start_walk
        if self.logger:
            self.logger.info(f"Scan discovery finished: {self.status.candidates} candidates in {self.status.walk_time:.2f}s")

    def _trigger_staging_merge(self):
        """Wait for queue to clear and trigger atomic merge."""
        with self._l1_lock:
            for root_id in list(self._l1_buffer.keys()):
                buffer = self._l1_buffer[root_id]
                if not buffer:
                    continue
                items = list(buffer.values())
                buffer.clear()
                rows = [item[0] for item in items]
                docs = [item[1] for item in items if item[1]]
                all_syms = []
                for item in items:
                    all_syms.extend(item[2])
                all_rels = []
                for item in items:
                    if len(item) > 3:
                        all_rels.extend(item[3])
                self.storage.enqueue_task(DbTask(kind="upsert_files_staging", rows=rows, engine_docs=docs))
                if all_syms:
                    self.storage.enqueue_task(DbTask(kind="upsert_symbols", rows=all_syms))
                if all_rels:
                    self.storage.enqueue_task(DbTask(kind="upsert_relations", rows=all_rels))
        self.storage.enqueue_task(DbTask(kind="staging_merge"))

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
                # 3. Pruning & Staging Merge: 스캔 완료 후 큐가 비었을 때 수행
                if self.status.index_ready and self._active_roots:
                    roots_to_prune = []
                    with self._l1_lock:
                        roots_to_prune = list(self._active_roots)
                        self._active_roots = []
                    
                    for rid in roots_to_prune:
                        count = self.db.prune_old_files(rid, self.status.last_scan_ts)
                        if count > 0 and self.logger:
                            self.logger.info(f"Pruned {count} dead files for {rid}")
                    
                    # Final Step: Atomic merge of staging data
                    self._trigger_staging_merge()
                    self.status.scan_finished_ts = int(time.time())
                    self.status.scan_duration_ms = max(0, (self.status.scan_finished_ts - self.status.scan_started_ts) * 1000)
                
                time.sleep(0.2)
                continue

            root_id, task = item
            try:
                self._handle_task(root_id, task)
            except Exception as e:
                if self.logger: self.logger.log_error(f"Task failed: {e}")

    def _handle_task(self, root_id: str, task: Dict[str, Any]):
        if task["kind"] == "scan_file":
            start_read = time.time()
            res = self.worker.process_file_task(task["root"], task["path"], task["st"], task["scan_ts"], time.time(), task["excluded"], root_id=root_id, force=task.get("force", False))
            elapsed = time.time() - start_read
            self.status.read_time += elapsed
            
            if elapsed > 0.1: # Track files taking > 100ms
                with self._l1_lock:
                    self._slow_files.append((str(task["path"]), elapsed * 1000))
                    self._slow_files.sort(key=lambda x: x[1], reverse=True)
                    self._slow_files = self._slow_files[:10]

            if not res:
                self.status.errors += 1
                try:
                    self.event_bus.publish("file_error", {"path": str(task.get("path", "")), "root_id": root_id})
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Event publish failed (file_error): {e}")
                return
            
            if res["type"] == "unchanged":
                self.status.skipped_unchanged += 1
                self.storage.enqueue_task(DbTask(kind="update_last_seen", paths=[res["rel"]]))
                try:
                    self.event_bus.publish("file_unchanged", {"path": res["rel"], "root_id": root_id})
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Event publish failed (file_unchanged): {e}")
                return
            
            # Case: File Changed or New
            self.status.indexed_new += 1
            rel_path = str(task["path"].relative_to(task["root"]))
            files_row = (
                res["rel"], rel_path, root_id, res["repo"], res["mtime"], res["size"], 
                res["content"], res.get("content_hash", ""), res.get("fts_content", ""), int(time.time()), 0, 
                res["parse_status"], res["parse_reason"], res["ast_status"], res["ast_reason"], 
                res["is_binary"], res["is_minified"], 0, res.get("content_bytes", len(res["content"])), res.get("metadata_json", "{}")
            )

            doc = res.get("engine_doc")
            sym_rows = []
            if res.get("symbols"):
                sym_rows = [(s[10], s[0], root_id, s[1]) + s[2:10] for s in res["symbols"]]
            rel_rows = []
            if res.get("relations"):
                for rel in res["relations"]:
                    if len(rel) < 8:
                        continue
                    from_path, from_symbol, from_sid, to_path, to_symbol, to_sid, rel_type, line = rel[:8]
                    from_root_id = from_path.split("/", 1)[0] if "/" in from_path else root_id
                    to_root_id = to_path.split("/", 1)[0] if (to_path and "/" in to_path) else from_root_id
                    rel_rows.append((
                        from_path,
                        from_root_id,
                        from_symbol,
                        from_sid or "",
                        to_path or "",
                        to_root_id,
                        to_symbol,
                        to_sid or "",
                        rel_type,
                        int(line or 0),
                        "{}",
                    ))

            self.status.parse_time += float(res.get("parse_elapsed", 0.0) or 0.0)
            ast_state = str(res.get("ast_status", "skipped"))
            if ast_state == "ok":
                self.status.ast_ok += 1
            elif ast_state == "failed":
                self.status.ast_failed += 1
            else:
                self.status.ast_skipped += 1
            self.status.symbols_emitted += len(sym_rows)
            self.status.relations_emitted += len(rel_rows)

            # LLM Freshness: High-priority events bypass L1 buffer
            if task.get("fast_track"):
                self.storage.upsert_files(rows=[files_row], engine_docs=[doc] if doc else [])
                if sym_rows:
                    self.storage.enqueue_task(DbTask(kind="upsert_symbols", rows=sym_rows))
                if rel_rows:
                    self.storage.enqueue_task(DbTask(kind="upsert_relations", rows=rel_rows))
                self.status.indexed_files += 1
                return

            with self._l1_lock:
                buffer = self._l1_buffer.setdefault(root_id, OrderedDict())
                # Efficient O(1) replacement of stale data in buffer
                buffer[files_row[0]] = (files_row, doc, sym_rows, rel_rows)

                if len(buffer) >= self._l1_max_size:
                    items = list(buffer.values())
                    buffer.clear()
                    
                    rows = [item[0] for item in items]
                    docs = [item[1] for item in items if item[1]]
                    all_syms = []
                    for item in items: all_syms.extend(item[2])
                    all_rels = []
                    for item in items:
                        if len(item) > 3:
                            all_rels.extend(item[3])
                    
                    # Use staging kind if flagged
                    kind = "upsert_files_staging" if task.get("use_staging") else "upsert_files"
                    self.storage.enqueue_task(DbTask(kind=kind, rows=rows, engine_docs=docs))
                    if all_syms:
                        self.storage.enqueue_task(DbTask(kind="upsert_symbols", rows=all_syms))
                    if all_rels:
                        self.storage.enqueue_task(DbTask(kind="upsert_relations", rows=all_rels))

            self.status.indexed_files += 1

            try:
                self.event_bus.publish("file_indexed", {"path": res["rel"], "root_id": root_id})
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Event publish failed (file_indexed): {e}")

    def _enqueue_fsevent(self, evt: FsEvent):
        evt_root = str(getattr(evt, "root", "") or "")
        if not evt_root:
            evt_root = self._infer_event_root(str(getattr(evt, "path", "") or ""))
        if not evt_root:
            if self.logger:
                self.logger.warning(f"Skip fs event without resolvable root: {evt}")
            return
        root_id = WorkspaceManager.root_id_for_workspace(evt_root)
        if evt.kind in (FsEventKind.CREATED, FsEventKind.MODIFIED):
            try:
                st = Path(evt.path).stat()
                self.coordinator.enqueue_priority(root_id, {
                    "kind": "scan_file", "root": Path(evt_root), "path": Path(evt.path), "st": st, "scan_ts": int(time.time()), "excluded": False,
                    "fast_track": True # Bypass L1 buffer for near-instant freshness
                }, base_priority=1.0)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to enqueue file event: {e}")
        elif evt.kind == FsEventKind.DELETED:
            rel_path = ""
            try:
                rel_path = Path(evt.path).relative_to(Path(evt_root)).as_posix()
            except Exception:
                try:
                    rel_path = os.path.relpath(str(evt.path), start=str(evt_root)).replace("\\", "/")
                except Exception:
                    rel_path = ""
            if not rel_path or rel_path.startswith("../") or rel_path == "..":
                if self.logger:
                    self.logger.warning(f"Skip delete event outside root (root={evt_root}, path={evt.path})")
                return
            db_path = f"{root_id}/{rel_path}"
            with self._l1_lock:
                if root_id in self._l1_buffer:
                    # Efficient O(1) removal from buffer if it was pending
                    self._l1_buffer[root_id].pop(db_path, None)
            self.storage.delete_file(path=db_path, engine_deletes=[db_path])
        elif evt.kind == FsEventKind.MOVED:
            # Old path is deleted.
            old_rel = ""
            try:
                old_rel = Path(evt.path).relative_to(Path(evt_root)).as_posix()
            except Exception:
                try:
                    old_rel = os.path.relpath(str(evt.path), start=str(evt_root)).replace("\\", "/")
                except Exception:
                    old_rel = ""
            if old_rel and not old_rel.startswith("../") and old_rel != "..":
                old_db_path = f"{root_id}/{old_rel}"
                with self._l1_lock:
                    if root_id in self._l1_buffer:
                        self._l1_buffer[root_id].pop(old_db_path, None)
                self.storage.delete_file(path=old_db_path, engine_deletes=[old_db_path])

            # New path should be indexed quickly if file exists.
            dst = str(getattr(evt, "dest_path", "") or "")
            if dst:
                dst_root = self._infer_event_root(dst) or evt_root
                try:
                    dst_path = Path(dst)
                    st = dst_path.stat()
                    dst_root_id = WorkspaceManager.root_id_for_workspace(dst_root)
                    self.coordinator.enqueue_priority(
                        dst_root_id,
                        {
                            "kind": "scan_file",
                            "root": Path(dst_root),
                            "path": dst_path,
                            "st": st,
                            "scan_ts": int(time.time()),
                            "excluded": False,
                            "fast_track": True,
                        },
                        base_priority=1.0,
                    )
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to enqueue moved destination: {e}")

    def _infer_event_root(self, event_path: str) -> str:
        if not event_path:
            return ""
        norm_path = WorkspaceManager.normalize_path(event_path)
        roots = [WorkspaceManager.normalize_path(r) for r in (self.cfg.workspace_roots or []) if r]
        roots.sort(key=len, reverse=True)
        for root in roots:
            if norm_path == root or norm_path.startswith(root + os.sep):
                return root
        return ""

    def stop(self):
        self._stop.set()
        if self.watcher: self.watcher.stop()
        with self._l1_lock:
            for root_id in list(self._l1_buffer.keys()):
                buffer = self._l1_buffer.pop(root_id)
                if buffer:
                    items = list(buffer.values())
                    rows = [item[0] for item in items]
                    docs = [item[1] for item in items if item[1]]
                    all_syms = []
                    for item in items: all_syms.extend(item[2])
                    all_rels = []
                    for item in items:
                        if len(item) > 3:
                            all_rels.extend(item[3])
                    
                    self.storage.upsert_files(rows=rows, engine_docs=docs)
                    if all_syms:
                        self.storage.enqueue_task(DbTask(kind="upsert_symbols", rows=all_syms))
                    if all_rels:
                        self.storage.enqueue_task(DbTask(kind="upsert_relations", rows=all_rels))
        for t in list(self._worker_threads):
            try:
                t.join(timeout=2.0)
            except Exception:
                pass
        self._worker_threads = []
        self._executor.shutdown(wait=True, cancel_futures=True)
    
    def get_queue_depths(self) -> Dict[str, int]:
        return {
            "fair_queue": self.coordinator.fair_queue.qsize(),
            "priority_queue": self.coordinator.priority_queue.qsize(),
            "db_writer": self.storage.writer.qsize()
        }

    def get_performance_metrics(self) -> Dict[str, Any]:
        metrics = self.storage.writer.get_performance_metrics()
        metrics.update({
            "candidates": self.status.candidates,
            "indexed_new": self.status.indexed_new,
            "skipped_unchanged": self.status.skipped_unchanged,
            "errors": self.status.errors,
            "scan_started_ts": self.status.scan_started_ts,
            "scan_finished_ts": self.status.scan_finished_ts,
            "scan_duration_ms": self.status.scan_duration_ms,
            "walk_time": round(self.status.walk_time, 2),
            "read_time": round(self.status.read_time, 2),
            "parse_time": round(self.status.parse_time, 2),
            "ast_ok": self.status.ast_ok,
            "ast_failed": self.status.ast_failed,
            "ast_skipped": self.status.ast_skipped,
            "symbols_emitted": self.status.symbols_emitted,
            "relations_emitted": self.status.relations_emitted,
            "db_time": metrics.get("db_time_total", 0.0),
            "slow_files": self._slow_files
        })
        return metrics
