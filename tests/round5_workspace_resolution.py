import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.workspace import WorkspaceManager


def test_resolve_config_path_deckard_env(tmp_path, monkeypatch):
    cfg = tmp_path / "deckard.json"
    cfg.write_text("{}")
    monkeypatch.setenv("DECKARD_CONFIG", str(cfg))
    monkeypatch.delenv("LOCAL_SEARCH_CONFIG", raising=False)
    assert WorkspaceManager.resolve_config_path(str(tmp_path)) == str(cfg)


def test_resolve_config_path_local_search_env(tmp_path, monkeypatch):
    cfg = tmp_path / "ls.json"
    cfg.write_text("{}")
    monkeypatch.delenv("DECKARD_CONFIG", raising=False)
    monkeypatch.setenv("LOCAL_SEARCH_CONFIG", str(cfg))
    assert WorkspaceManager.resolve_config_path(str(tmp_path)) == str(cfg)


def test_resolve_config_path_workspace_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DECKARD_CONFIG", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_CONFIG", raising=False)
    cfg = tmp_path / ".codex" / "tools" / "deckard" / "config" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("{}")
    assert WorkspaceManager.resolve_config_path(str(tmp_path)) == str(cfg)


def test_resolve_workspace_root_from_root_uri(tmp_path):
    root_uri = f"file://{tmp_path}"
    assert WorkspaceManager.resolve_workspace_root(root_uri) == str(tmp_path.absolute())


def test_resolve_workspace_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("LOCAL_SEARCH_WORKSPACE_ROOT", raising=False)
    assert WorkspaceManager.resolve_workspace_root(None) == str(tmp_path.absolute())
