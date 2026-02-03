import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.workspace import WorkspaceManager


def test_root_uri_over_env(tmp_path, monkeypatch):
    env_root = tmp_path / "env"
    env_root.mkdir()
    uri_root = tmp_path / "uri"
    uri_root.mkdir()

    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", str(env_root))
    resolved = WorkspaceManager.resolve_workspace_root(f"file://{uri_root}")
    assert resolved == str(uri_root.absolute())


def test_env_over_cwd(monkeypatch, tmp_path):
    env_root = tmp_path / "env"
    env_root.mkdir()
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", str(env_root))
    resolved = WorkspaceManager.resolve_workspace_root(None)
    assert resolved == str(env_root.absolute())


def test_codex_root_marker_detection(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".codex-root").write_text("")
    child = ws / "child"
    child.mkdir()

    monkeypatch.chdir(child)
    monkeypatch.delenv("DECKARD_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_WORKSPACE_ROOT", raising=False)

    resolved = WorkspaceManager.resolve_workspace_root(None)
    assert resolved == str(ws.absolute())


def test_invalid_root_uri_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("DECKARD_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_WORKSPACE_ROOT", raising=False)

    monkeypatch.chdir(tmp_path)
    resolved = WorkspaceManager.resolve_workspace_root("file:///nonexistent/path")
    assert resolved == str(tmp_path)


def test_env_cwd_placeholder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", "${cwd}")
    resolved = WorkspaceManager.resolve_workspace_root(None)
    assert resolved == str(tmp_path)
