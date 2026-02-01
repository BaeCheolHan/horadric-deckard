#!/usr/bin/env python3
"""
Telemetry and logging for Local Search MCP Server.
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
try:
    from app.indexer import _redact
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
        self.log_dir = log_dir
    
    def log_error(self, message: str) -> None:
        """Log error message to stderr and file."""
        print(f"[deckard] ERROR: {message}", file=sys.stderr, flush=True)
        self._write_to_file(f"[ERROR] {message}")
    
    def log_info(self, message: str) -> None:
        """Log info message to stderr and file."""
        print(f"[deckard] INFO: {message}", file=sys.stderr, flush=True)
        self._write_to_file(f"[INFO] {message}")
    
    def log_telemetry(self, message: str) -> None:
        """
        Log telemetry to file.
        
        Args:
            message: Telemetry message to log
        """
        self._write_to_file(message)

    def _write_to_file(self, message: str) -> None:
        """Helper to write message with timestamp to log file."""
        if not self.log_dir:
            return
        
        # Redact secrets before writing to disk
        message = _redact(message)
        
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / "deckard.log"
            
            timestamp = datetime.now().astimezone().isoformat()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception as e:
            print(f"[deckard] ERROR: Failed to log to file: {e}", file=sys.stderr, flush=True)
