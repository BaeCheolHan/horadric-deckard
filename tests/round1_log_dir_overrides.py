import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.workspace import WorkspaceManager
from mcp.telemetry import TelemetryLogger


def test_get_global_log_dir_deckard_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("LOCAL_SEARCH_LOG_DIR", raising=False)
    assert WorkspaceManager.get_global_log_dir() == (tmp_path / "logs")


def test_get_global_log_dir_local_search_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DECKARD_LOG_DIR", raising=False)
    monkeypatch.setenv("LOCAL_SEARCH_LOG_DIR", str(tmp_path / "lslogs"))
    assert WorkspaceManager.get_global_log_dir() == (tmp_path / "lslogs")


def test_get_global_log_dir_default(monkeypatch):
    monkeypatch.delenv("DECKARD_LOG_DIR", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_LOG_DIR", raising=False)
    expected = Path.home() / ".local" / "share" / "deckard" / "logs"
    assert WorkspaceManager.get_global_log_dir() == expected


def test_telemetry_logger_writes_file(tmp_path):
    logger = TelemetryLogger(tmp_path)
    logger.log_info("hello")
    log_file = tmp_path / "deckard.log"
    assert log_file.exists()
    assert "[INFO] hello" in log_file.read_text()


def test_telemetry_logger_handles_unwritable_dir(tmp_path):
    unwritable = tmp_path / "ro"
    unwritable.mkdir()
    os.chmod(unwritable, 0o500)
    logger = TelemetryLogger(unwritable)
    # Should not raise even if file write fails
    logger.log_info("no-crash")
