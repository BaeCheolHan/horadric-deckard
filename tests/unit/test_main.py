import json
import os
import signal
import threading
from pathlib import Path

import pytest

import app.main as main_mod


class DummyDB:
    def __init__(self, path):
        self.path = path
        self.closed = False

    def close(self):
        self.closed = True


class DummyIndexer:
    def __init__(self, cfg, db):
        self.cfg = cfg
        self.db = db
        self.stopped = False

    def run_forever(self):
        return None

    def stop(self):
        self.stopped = True


class DummyHTTPD:
    def __init__(self):
        self.closed = False

    def shutdown(self):
        self.closed = True


def test_main_happy_path(monkeypatch, tmp_path):
    handlers = {}

    def fake_signal(sig, handler):
        handlers[sig] = handler
        return None

    def fake_serve_forever(host, port, db, indexer, version="dev"):
        return DummyHTTPD(), port + 1

    monkeypatch.setattr(main_mod, "LocalSearchDB", DummyDB)
    monkeypatch.setattr(main_mod, "Indexer", DummyIndexer)
    monkeypatch.setattr(main_mod, "serve_forever", fake_serve_forever)
    monkeypatch.setattr(main_mod.signal, "signal", fake_signal)

    class DummyWM:
        @staticmethod
        def resolve_workspace_root():
            return str(tmp_path)

    monkeypatch.setattr(main_mod, "WorkspaceManager", DummyWM)

    def fake_sleep(_):
        if signal.SIGINT in handlers:
            handlers[signal.SIGINT]()

    monkeypatch.setattr(main_mod.time, "sleep", fake_sleep)

    rc = main_mod.main()
    assert rc == 0

    server_json = tmp_path / ".codex" / "tools" / "deckard" / "data" / "server.json"
    assert server_json.exists()
    info = json.loads(server_json.read_text(encoding="utf-8"))
    assert info["host"] == "127.0.0.1"


def test_main_rejects_non_loopback(monkeypatch, tmp_path):
    class DummyWM:
        @staticmethod
        def resolve_workspace_root():
            return str(tmp_path)

    monkeypatch.setattr(main_mod, "WorkspaceManager", DummyWM)
    monkeypatch.setenv("LOCAL_SEARCH_ALLOW_NON_LOOPBACK", "0")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"server_host": "0.0.0.0"}), encoding="utf-8")

    monkeypatch.setattr(main_mod, "resolve_config_path", lambda _: str(cfg_path))

    with pytest.raises(SystemExit):
        main_mod.main()
