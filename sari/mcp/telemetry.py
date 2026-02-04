#!/usr/bin/env python3
"""
Telemetry and logging for Local Search MCP Server.
"""
import sys
import queue
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
try:
    from sari.core.indexer import _redact
except ImportError:
    # Fallback if imports fail (e.g. running script standalone without path)
    # But usually app is in path.
    def _redact(t): return t

class TelemetryLogger:
    """Handles logging and telemetry for MCP server."""

    def __init__(self, log_dir: Optional[Path] = None):
        """
        Initialize telemetry logger.

        Args:
            log_dir: Directory for log files. If None, uses global log dir.
        """
        self.log_dir = Path(log_dir) if log_dir else None
        self._queue: Optional[queue.Queue] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._drop_count = 0
        self._backlog_limit = 1000

        if self.log_dir:
            self._queue = queue.Queue()
            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()

    def log_error(self, message: str) -> None:
        """Log error message to stderr and file."""
        print(f"[sari] ERROR: {message}", file=sys.stderr, flush=True)
        self._enqueue(f"[ERROR] {message}")

    def log_info(self, message: str) -> None:
        """Log info message to stderr and file."""
        print(f"[sari] INFO: {message}", file=sys.stderr, flush=True)
        self._enqueue(f"[INFO] {message}")

    def log_telemetry(self, message: str) -> None:
        """
        Log telemetry to file.

        Args:
            message: Telemetry message to log
        """
        self._enqueue(message)

    def _enqueue(self, message: str) -> None:
        if not self._queue:
            return
        if self._queue.qsize() > self._backlog_limit:
            self._drop_count += 1
            return
        self._queue.put(message)

    def _writer_loop(self) -> None:
        if not self.log_dir:
            return
        while not self._stop_event.is_set() or (self._queue and not self._queue.empty()):
            try:
                msg = self._queue.get(timeout=0.2) if self._queue else None
            except queue.Empty:
                continue
            if msg is None:
                continue
            self._write_to_file(msg)
            if self._queue:
                self._queue.task_done()

    def _write_to_file(self, message: str) -> None:
        """Helper to write message with timestamp to log file."""
        if not self.log_dir:
            return

        # Redact secrets before writing to disk
        message = _redact(message)

        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / "sari.log"

            timestamp = datetime.now().astimezone().isoformat()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception as e:
            print(f"[sari] ERROR: Failed to log to file: {e}", file=sys.stderr, flush=True)

    def stop(self, timeout: float = 2.0) -> None:
        if not self._queue or not self._writer_thread:
            return
        self._stop_event.set()
        self._writer_thread.join(timeout=timeout)

    def get_queue_depth(self) -> int:
        if not self._queue:
            return 0
        return self._queue.qsize()

    def get_drop_count(self) -> int:
        return self._drop_count