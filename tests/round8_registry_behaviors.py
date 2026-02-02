import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.registry import ServerRegistry


def test_load_invalid_json_returns_empty(tmp_path):
    reg_dir = tmp_path / "reg"
    reg_dir.mkdir()
    reg_file = reg_dir / "server.json"
    reg_file.write_text("{broken}")

    with patch("app.registry.REGISTRY_FILE", reg_file), patch("app.registry.REGISTRY_DIR", reg_dir):
        reg = ServerRegistry()
        data = reg._load()
        assert data.get("instances") == {}


def test_register_normalizes_path(tmp_path):
    reg_dir = tmp_path / "reg"
    reg_dir.mkdir()
    reg_file = reg_dir / "server.json"

    with patch("app.registry.REGISTRY_FILE", reg_file), patch("app.registry.REGISTRY_DIR", reg_dir):
        reg = ServerRegistry()
        ws = reg_dir / ".." / "ws"
        ws.mkdir()
        reg.register(str(ws), 50111, 1234)
        data = reg._load()
        assert str(ws.resolve()) in data.get("instances", {})


def test_unregister_removes_entry(tmp_path):
    reg_dir = tmp_path / "reg"
    reg_dir.mkdir()
    reg_file = reg_dir / "server.json"

    with patch("app.registry.REGISTRY_FILE", reg_file), patch("app.registry.REGISTRY_DIR", reg_dir):
        reg = ServerRegistry()
        ws = reg_dir / "ws"
        ws.mkdir()
        reg.register(str(ws), 50112, 1234)
        reg.unregister(str(ws))
        data = reg._load()
        assert str(ws.resolve()) not in data.get("instances", {})


def test_get_instance_returns_none_for_dead_pid(tmp_path, monkeypatch):
    reg_dir = tmp_path / "reg"
    reg_dir.mkdir()
    reg_file = reg_dir / "server.json"

    with patch("app.registry.REGISTRY_FILE", reg_file), patch("app.registry.REGISTRY_DIR", reg_dir):
        reg = ServerRegistry()
        ws = reg_dir / "ws"
        ws.mkdir()
        reg.register(str(ws), 50113, 999999)
        monkeypatch.setattr(reg, "_is_process_alive", lambda pid: False)
        assert reg.get_instance(str(ws)) is None


def test_find_free_port_skips_used_ports(tmp_path):
    reg_dir = tmp_path / "reg"
    reg_dir.mkdir()
    reg_file = reg_dir / "server.json"

    with patch("app.registry.REGISTRY_FILE", reg_file), patch("app.registry.REGISTRY_DIR", reg_dir):
        reg = ServerRegistry()
        ws = reg_dir / "ws"
        ws.mkdir()
        reg.register(str(ws), 50120, 1234)

        class FakeSocket:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def bind(self, addr):
                host, port = addr
                if port == 50120:
                    raise OSError("in use")
                return None

        with patch("app.registry.socket.socket", return_value=FakeSocket()):
            port = reg.find_free_port(start_port=50120, max_port=50121)
            assert port == 50121
