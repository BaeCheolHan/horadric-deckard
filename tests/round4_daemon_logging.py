import os
import sys
import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mcp.daemon as daemon


def test_resolve_log_dir_deckard_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("LOCAL_SEARCH_LOG_DIR", raising=False)
    assert daemon._resolve_log_dir() == (tmp_path / "logs")


def test_resolve_log_dir_local_search_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DECKARD_LOG_DIR", raising=False)
    monkeypatch.setenv("LOCAL_SEARCH_LOG_DIR", str(tmp_path / "lslogs"))
    assert daemon._resolve_log_dir() == (tmp_path / "lslogs")


def test_resolve_log_dir_default(monkeypatch):
    monkeypatch.delenv("DECKARD_LOG_DIR", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_LOG_DIR", raising=False)
    expected = Path.home() / ".local" / "share" / "deckard"
    assert daemon._resolve_log_dir() == expected


def test_init_logging_fallback_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("DECKARD_LOG_DIR", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_LOG_DIR", raising=False)

    calls = {"n": 0}
    orig_mkdir = Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("no")
        return orig_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    daemon._init_logging()


def test_init_logging_no_crash_on_all_fail(monkeypatch):
    monkeypatch.setenv("TMPDIR", "/tmp")
    monkeypatch.delenv("DECKARD_LOG_DIR", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_LOG_DIR", raising=False)

    def always_fail(*args, **kwargs):
        raise PermissionError("no")

    monkeypatch.setattr(Path, "mkdir", always_fail)
    monkeypatch.setattr(daemon.logging, "FileHandler", MagicMock(side_effect=PermissionError("no")))
    daemon._init_logging()
