
import os
import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    # Dummy classes for safe definition
    class FileSystemEventHandler: pass
    class Observer: pass

try:
    from .queue_pipeline import FsEvent, FsEventKind
except Exception:
    from queue_pipeline import FsEvent, FsEventKind
try:
    from .workspace import WorkspaceManager
except Exception:
    from workspace import WorkspaceManager

def _is_git_event(path: str) -> bool:
    if not path:
        return False
    if not isinstance(path, str):
        return False
    norm = path.replace("\\", "/")
    if "/.git/" in norm or norm.endswith("/.git"):
        return True
    base = os.path.basename(norm)
    return base in {"HEAD", "index", "packed-refs", "ORIG_HEAD", "FETCH_HEAD"}


class DebouncedEventHandler(FileSystemEventHandler):
    """Handles events with debounce to prevent duplicate indexing on save."""
    def __init__(
        self,
        callback: Callable[[str], None],
        debounce_seconds: float = 0.1, # Lower default
        logger=None,
        git_callback: Optional[Callable[[str], None]] = None,
        git_debounce_seconds: float = 3.0,
    ):
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self.logger = logger
        self.git_callback = git_callback
        self.git_debounce_seconds = git_debounce_seconds
        self._timers = {}
        self._lock = threading.Lock()
        self._pending_events: Dict[str, FsEvent] = {}
        self._git_timer: Optional[threading.Timer] = None
        self._git_last_path: str = ""
        self._event_times = deque(maxlen=200)

        # Adaptive debounce (ms) and rate window (sec)
        # LLM Freshness: 100ms minimum debounce is now standard.
        self._debounce_min = 0.1
        self._debounce_max = 1.0
        self._debounce_target_rps = 50.0
        self._rate_window = 1.0

        # Token bucket for burst control
        self._bucket_capacity = 100.0
        self._bucket_rate = 50.0
        self._bucket_tokens = self._bucket_capacity
        self._bucket_last_ts = time.time()
        self._bucket_flush_seconds = 0.1
        self._bucket_timer: Optional[threading.Timer] = None

    def on_any_event(self, event):
        if event.is_directory:
            return

        # We care about Created, Modified, Moved, Deleted
        # watchdog event types: 'created', 'deleted', 'modified', 'moved'

        evt_kind = None
        if event.event_type == 'created':
            evt_kind = FsEventKind.CREATED
        elif event.event_type == 'modified':
            evt_kind = FsEventKind.MODIFIED
        elif event.event_type == 'deleted':
            evt_kind = FsEventKind.DELETED
        elif event.event_type == 'moved':
            evt_kind = FsEventKind.MOVED

        if not evt_kind:
            return

        src_path = getattr(event, "src_path", "")
        if not isinstance(src_path, str):
            return
        dest_path = getattr(event, "dest_path", "")
        if not isinstance(dest_path, str):
            dest_path = ""

        key = src_path
        if _is_git_event(src_path) or _is_git_event(dest_path):
            if self.git_callback:
                with self._lock:
                    if self._git_timer:
                        self._git_timer.cancel()
                    self._git_last_path = src_path
                    self._git_timer = threading.Timer(self.git_debounce_seconds, self._trigger_git)
                    self._git_timer.start()
            if self.logger:
                self.logger.log_info("Git activity detected; deferring to rescan.")
            return
        fs_event = FsEvent(kind=evt_kind, path=src_path,
                           dest_path=dest_path or None,
                           ts=time.time())

        with self._lock:
            # Adaptive debounce update
            self._update_debounce(fs_event.ts)

            # Burst control: token bucket
            if not self._try_consume_token(fs_event.ts):
                if key in self._timers:
                    self._timers[key].cancel()
                    del self._timers[key]
                self._pending_events[key] = fs_event
                self._schedule_bucket_flush()
                return

            if key in self._timers:
                self._timers[key].cancel()
            self._pending_events[key] = fs_event
            t = threading.Timer(self.debounce_seconds, self._trigger, args=[key])
            self._timers[key] = t
            t.start()

    def _trigger(self, path: str):
        with self._lock:
            if path in self._timers:
                del self._timers[path]
            fs_event = self._pending_events.pop(path, None)
        if not fs_event:
            return
        try:
           self.callback(fs_event)
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Watcher callback failed for {path}: {e}")

    def _update_debounce(self, now_ts: float) -> None:
        self._event_times.append(now_ts)
        # Drop old events outside window
        while self._event_times and now_ts - self._event_times[0] > self._rate_window:
            self._event_times.popleft()
        rate = len(self._event_times) / max(0.5, self._rate_window)
        scale = max(1.0, rate / max(1.0, self._debounce_target_rps))
        self.debounce_seconds = min(self._debounce_max, max(self._debounce_min, self._debounce_min * scale))

    def _refill_tokens(self, now_ts: float) -> None:
        elapsed = max(0.0, now_ts - self._bucket_last_ts)
        if elapsed > 0:
            self._bucket_tokens = min(self._bucket_capacity, self._bucket_tokens + elapsed * self._bucket_rate)
            self._bucket_last_ts = now_ts

    def _try_consume_token(self, now_ts: float) -> bool:
        self._refill_tokens(now_ts)
        if self._bucket_tokens >= 1.0:
            self._bucket_tokens -= 1.0
            return True
        return False

    def _schedule_bucket_flush(self) -> None:
        if self._bucket_timer and self._bucket_timer.is_alive():
            return
        self._bucket_timer = threading.Timer(max(0.1, self._bucket_flush_seconds), self._flush_bucket)
        self._bucket_timer.start()

    def _flush_bucket(self) -> None:
        to_dispatch: List[FsEvent] = []
        with self._lock:
            now = time.time()
            self._refill_tokens(now)
            items = sorted(self._pending_events.items(), key=lambda kv: kv[1].ts)
            self._pending_events = {}
            for key, evt in items:
                if self._bucket_tokens >= 1.0:
                    self._bucket_tokens -= 1.0
                    to_dispatch.append(evt)
                else:
                    self._pending_events[key] = evt
            if self._pending_events:
                self._bucket_timer = threading.Timer(max(0.1, self._bucket_flush_seconds), self._flush_bucket)
                self._bucket_timer.start()
            else:
                self._bucket_timer = None
        for evt in to_dispatch:
            try:
                self.callback(evt)
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Watcher callback failed for {evt.path}: {e}")

    def _trigger_git(self):
        path = ""
        with self._lock:
            path = self._git_last_path
            self._git_timer = None
        try:
            if self.git_callback:
                self.git_callback(path or ".git")
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Watcher git callback failed for {path}: {e}")

class FileWatcher:
    def __init__(
        self,
        paths: List[str],
        on_change_callback: Callable[[FsEvent], None],
        logger=None,
        on_git_checkout: Optional[Callable[[str], None]] = None,
        event_bus=None,
    ):
        self.paths = paths
        self.callback = on_change_callback
        self.logger = logger
        self.git_callback = on_git_checkout
        self.event_bus = event_bus
        self.observer = None
        self._running = False
        self._monitor_thread = None
        self._stop_event = threading.Event()

    def start(self):
        if not HAS_WATCHDOG:
            if self.logger:
                self.logger.log_info("Watchdog not installed. Skipping real-time monitoring.")
            return

        if self._running:
            return

        # High-performance observer with low timeout (latency)
        self.observer = Observer(timeout=0.1)
        try:
            git_debounce = float(os.environ.get("SARI_GIT_CHECKOUT_DEBOUNCE", "3") or 3)
        except Exception:
            git_debounce = 3.0
        handler = DebouncedEventHandler(
            self._dispatch_event,
            logger=self.logger,
            git_callback=self.git_callback,
            git_debounce_seconds=max(1.0, git_debounce),
        )

        started_any = False
        for p in self.paths:
            if os.path.exists(p):
                try:
                    self.observer.schedule(handler, p, recursive=True)
                    started_any = True
                except Exception as e:
                    if self.logger:
                        self.logger.log_error(f"Failed to watch path {p}: {e}")

        if started_any:
            try:
                self.observer.start()
                self._running = True
                self._start_monitor()
                if self.logger:
                    self.logger.log_info(f"Watcher started on: {self.paths}")
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Failed to start observer: {e}")

    def stop(self):
        self._stop_event.set()
        if self.observer and self._running:
            self.observer.stop()
            self.observer.join()
            self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)

    def _start_monitor(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _restart_observer(self):
        try:
            if self.observer:
                try:
                    self.observer.stop()
                    self.observer.join(timeout=1.0)
                except Exception:
                    pass
            self.observer = Observer()
            try:
                git_debounce = float(os.environ.get("SARI_GIT_CHECKOUT_DEBOUNCE", "3") or 3)
            except Exception:
                git_debounce = 3.0
            handler = DebouncedEventHandler(
                self._dispatch_event,
                logger=self.logger,
                git_callback=self.git_callback,
                git_debounce_seconds=max(1.0, git_debounce),
            )
            started_any = False
            for p in self.paths:
                if os.path.exists(p):
                    try:
                        self.observer.schedule(handler, p, recursive=True)
                        started_any = True
                    except Exception as e:
                        if self.logger:
                            self.logger.log_error(f"Failed to watch path {p}: {e}")
            if started_any:
                self.observer.start()
                self._running = True
                if self.logger:
                    self.logger.log_info("Watcher restarted.")
            else:
                if self.logger:
                    self.logger.log_error("Watcher restart failed: no valid paths.")
                self._running = False
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Watcher restart failed: {e}")
            self._running = False

    def _monitor_loop(self):
        try:
            interval = float(os.environ.get("SARI_WATCHER_MONITOR_SECONDS", "10"))
        except Exception:
            interval = 10.0
        while not self._stop_event.is_set():
            time.sleep(max(1.0, interval))
            if self._stop_event.is_set():
                break
            if self.observer and not self.observer.is_alive() and self._running:
                if self.logger:
                    self.logger.log_error("Watcher observer died; restarting.")
                self._restart_observer()

    def _dispatch_event(self, evt: FsEvent):
        normalized_evt = evt
        try:
            if not getattr(evt, "root", ""):
                inferred_root = self._infer_root_for_path(getattr(evt, "path", ""))
                if inferred_root:
                    normalized_evt = FsEvent(
                        kind=evt.kind,
                        path=evt.path,
                        root=inferred_root,
                        dest_path=evt.dest_path,
                        ts=evt.ts,
                    )
        except Exception:
            normalized_evt = evt

        if self.event_bus:
            try:
                self.event_bus.publish("fs_event", normalized_evt)
                return
            except Exception:
                pass
        try:
            self.callback(normalized_evt)
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Watcher callback failed for {getattr(normalized_evt, 'path', '')}: {e}")

    def _infer_root_for_path(self, event_path: str) -> str:
        if not event_path:
            return ""
        norm_event = WorkspaceManager.normalize_path(event_path)
        roots = [WorkspaceManager.normalize_path(p) for p in self.paths if p]
        roots.sort(key=len, reverse=True)
        for root in roots:
            if norm_event == root or norm_event.startswith(root + os.sep):
                return root
        return ""
