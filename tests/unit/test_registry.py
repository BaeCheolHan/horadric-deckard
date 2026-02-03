import importlib
import json
import os
import socket
from pathlib import Path

import pytest


def _load_registry(tmp_path, monkeypatch):
    reg_file = tmp_path / "server.json"
    monkeypatch.setenv("DECKARD_REGISTRY_FILE", str(reg_file))
    import app.registry as registry
    importlib.reload(registry)
    return registry


def test_registry_register_unregister(tmp_path, monkeypatch):
    registry = _load_registry(tmp_path, monkeypatch)
    reg = registry.ServerRegistry()
    root = str(tmp_path / "repo")
    reg.register(root, 1234, os.getpid())
    inst = reg.get_instance(root)
    assert inst is not None
    reg.unregister(root)
    inst = reg.get_instance(root)
    assert inst is None

    # _save/_load paths
    reg._save({"version": "1.0", "instances": {}})
    assert reg._load().get("instances") == {}

    # invalid JSON on unregister
    reg_file = registry.REGISTRY_FILE
    reg_file.write_text("not-json", encoding="utf-8")
    reg.unregister(root)


def test_registry_find_free_port(tmp_path, monkeypatch):
    registry = _load_registry(tmp_path, monkeypatch)
    reg = registry.ServerRegistry()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    occupied = sock.getsockname()[1]
    try:
        port = reg.find_free_port(start_port=occupied, max_port=occupied + 2)
        assert port != occupied
    finally:
        sock.close()

    # no free port path
    with pytest.raises(RuntimeError):
        reg.find_free_port(start_port=1, max_port=0)
