import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mcp.cli as cli


def _args():
    return types.SimpleNamespace()


def test_tcp_blocked_helper():
    err = OSError(1, "blocked")
    assert cli._tcp_blocked(err) is True
    err = OSError(13, "blocked")
    assert cli._tcp_blocked(err) is True
    err = OSError(111, "refused")
    assert cli._tcp_blocked(err) is False


def test_cmd_auto_fallback_on_tcp_blocked(monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError(1, "blocked")

    monkeypatch.setattr(cli.socket, "create_connection", _raise)

    called = {"server": 0}
    def fake_server_main():
        called["server"] += 1

    monkeypatch.setattr("mcp.server.main", fake_server_main, raising=False)
    res = cli.cmd_auto(_args())
    assert res == 0
    assert called["server"] == 1


def test_cmd_auto_uses_proxy_when_tcp_ok(monkeypatch):
    class DummyConn:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
    monkeypatch.setattr(cli.socket, "create_connection", lambda *a, **k: DummyConn())

    called = {"proxy": 0}
    def fake_proxy(args):
        called["proxy"] += 1
        return 0

    monkeypatch.setattr(cli, "cmd_proxy", fake_proxy)
    res = cli.cmd_auto(_args())
    assert res == 0
    assert called["proxy"] == 1


def test_cmd_auto_starts_daemon_then_proxy(monkeypatch):
    states = {"running": False}

    def fake_is_running(*args, **kwargs):
        # First call False, then True
        if not states["running"]:
            states["running"] = True
            return False
        return True

    monkeypatch.setattr(cli, "is_daemon_running", fake_is_running)
    monkeypatch.setattr(cli.socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError(111, "refused")))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cli.time, "sleep", lambda *a, **k: None)

    called = {"proxy": 0}
    def fake_proxy(args):
        called["proxy"] += 1
        return 0

    monkeypatch.setattr(cli, "cmd_proxy", fake_proxy)
    res = cli.cmd_auto(_args())
    assert res == 0
    assert called["proxy"] == 1


def test_cmd_auto_fallback_when_daemon_never_starts(monkeypatch):
    monkeypatch.setattr(cli, "is_daemon_running", lambda *a, **k: False)
    monkeypatch.setattr(cli.socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError(111, "refused")))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cli.time, "sleep", lambda *a, **k: None)

    called = {"server": 0}
    def fake_server_main():
        called["server"] += 1

    monkeypatch.setattr("mcp.server.main", fake_server_main, raising=False)
    res = cli.cmd_auto(_args())
    assert res == 0
    assert called["server"] == 1
