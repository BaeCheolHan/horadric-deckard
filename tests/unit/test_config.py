import json
import logging
from pathlib import Path

import pytest

from app.config import Config, resolve_config_path


def test_config_defaults(tmp_path):
    cfg = Config.get_defaults(str(tmp_path))
    assert cfg["workspace_root"] == str(tmp_path)
    assert cfg["workspace_roots"] == [str(tmp_path)]
    assert cfg["server_port"] == 47777


def test_config_load_legacy_and_env(tmp_path, monkeypatch, caplog):
    cfg_path = tmp_path / "config.json"
    raw = {
        "indexing": {
            "include_extensions": [".py"],
            "exclude_patterns": ["build", "*.lock"],
        },
        "server_port": 12345,
        "db_path": "relative.db",
    }
    cfg_path.write_text(json.dumps(raw), encoding="utf-8")

    monkeypatch.setenv("DECKARD_PORT", "23456")
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", str(tmp_path))

    caplog.set_level(logging.WARNING)
    cfg = Config.load(str(cfg_path))

    assert cfg.server_port == 23456
    assert cfg.include_ext == [".py"]
    assert "build" in cfg.exclude_dirs
    assert "*.lock" in cfg.exclude_globs
    assert cfg.db_path != "relative.db"


def test_config_load_env_db_path(tmp_path, monkeypatch, caplog):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("DECKARD_DB_PATH", "relative.db")
    caplog.set_level(logging.WARNING)
    cfg = Config.load(str(cfg_path), workspace_root_override=str(tmp_path))
    assert str(tmp_path) in cfg.db_path


def test_resolve_config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", str(tmp_path))
    path = resolve_config_path(str(tmp_path))
    assert isinstance(path, str)
