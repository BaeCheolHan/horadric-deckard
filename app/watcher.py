
import os
import time
import threading
from typing import Callable, List, Optional
from threading import Timer

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    # Dummy classes for safe definition
    class FileSystemEventHandler: pass
    class Observer: pass

class DebouncedEventHandler(FileSystemEventHandler):
    """Handles events with debounce to prevent duplicate indexing on save."""
    def __init__(self, callback: Callable[[str], None], debounce_seconds: float = 1.0, logger=None):
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self.logger = logger
        self._timers = {}
        self._lock = threading.Lock()

    def on_any_event(self, event):
        if event.is_directory:
            return
        
        # We care about Created, Modified, Moved, Deleted
        # watchdog event types: 'created', 'deleted', 'modified', 'moved'
        
        path = event.src_path
        if event.event_type == 'moved':
             # For moved, we might want to process dest_path too
             # But let's just trigger for src_path handling (deletion/change)
             pass
        
        with self._lock:
            if path in self._timers:
                self._timers[path].cancel()
            
            t = Timer(self.debounce_seconds, self._trigger, args=[path])
            self._timers[path] = t
            t.start()

    def _trigger(self, path: str):
        with self._lock:
            if path in self._timers:
                del self._timers[path]
        
        try:
           self.callback(path)
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Watcher callback failed for {path}: {e}")

class FileWatcher:
    def __init__(self, paths: List[str], on_change_callback: Callable[[str], None], logger=None):
        self.paths = paths
        self.callback = on_change_callback
        self.logger = logger
        self.observer = None
        self._running = False

    def start(self):
        if not HAS_WATCHDOG:
            if self.logger:
                self.logger.log_info("Watchdog not installed. Skipping real-time monitoring.")
            return

        if self._running:
            return

        self.observer = Observer()
        handler = DebouncedEventHandler(self.callback, logger=self.logger)
        
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
                if self.logger:
                    self.logger.log_info(f"Watcher started on: {self.paths}")
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Failed to start observer: {e}")

    def stop(self):
        if self.observer and self._running:
            self.observer.stop()
            self.observer.join()
            self._running = False
