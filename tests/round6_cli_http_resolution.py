import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mcp.cli as cli
from app.registry import ServerRegistry
from app.workspace import WorkspaceManager


def test_get_http_host_port_from_registry(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(WorkspaceManager, "resolve_workspace_root", lambda: str(ws))

    def fake_get_instance(self, root):
        return {"host": "127.0.0.1", "port": 50123}

    monkeypatch.setattr(ServerRegistry, "get_instance", fake_get_instance)
    host, port = cli._get_http_host_port()
    assert host == "127.0.0.1"
    assert port == 50123


def test_get_http_host_port_from_server_json(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(WorkspaceManager, "resolve_workspace_root", lambda: str(ws))

    data_dir = ws / ".codex" / "tools" / "deckard" / "data"
    data_dir.mkdir(parents=True)
    server_json = data_dir / "server.json"
    server_json.write_text(json.dumps({"host": "127.0.0.1", "port": 50055}))

    with patch.object(ServerRegistry, "get_instance", return_value=None):
        host, port = cli._get_http_host_port()
    assert host == "127.0.0.1"
    assert port == 50055


def test_get_http_host_port_from_workspace_config(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(WorkspaceManager, "resolve_workspace_root", lambda: str(ws))

    cfg_dir = ws / ".codex" / "tools" / "deckard" / "config"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps({"server_host": "127.0.0.1", "server_port": 50077}))

    with patch.object(ServerRegistry, "get_instance", return_value=None):
        host, port = cli._get_http_host_port()
    assert host == "127.0.0.1"
    assert port == 50077


def test_get_http_host_port_from_packaged_config(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(WorkspaceManager, "resolve_workspace_root", lambda: str(ws))

    with patch.object(ServerRegistry, "get_instance", return_value=None):
        host, port = cli._get_http_host_port()
    assert host == "127.0.0.1"
    assert port == 47777


def test_enforce_loopback_rejects_non_loopback(monkeypatch):
    monkeypatch.delenv("DECKARD_ALLOW_NON_LOOPBACK", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_ALLOW_NON_LOOPBACK", raising=False)
    with pytest.raises(RuntimeError):
        cli._enforce_loopback("192.168.0.10")
