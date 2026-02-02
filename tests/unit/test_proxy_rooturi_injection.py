import json
import types
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mcp.proxy as proxy


def _make_init(params=None):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": params or {"protocolVersion": "2025-11-25", "capabilities": {}},
    }


def _wrap(body: bytes) -> bytes:
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def test_inject_rooturi_single_message(monkeypatch):
    msg = json.dumps(_make_init()).encode("utf-8")

    sent = {}
    class FakeSock:
        def sendall(self, b):
            sent["payload"] = b

    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", "/tmp/ws")

    # Run one iteration of forward_stdin_to_socket by ending stream after one message
    def _read_mcp_message(_):
        return msg, "framed"

    monkeypatch.setattr(proxy, "_read_mcp_message", _read_mcp_message)

    # Stop after one iteration
    def _stop(*args, **kwargs):
        raise SystemExit()
    monkeypatch.setattr(proxy, "_read_mcp_message", lambda _: _read_mcp_message(_) if not sent else (_stop()))

    with pytest.raises(SystemExit):
        proxy.forward_stdin_to_socket(FakeSock(), {"mode": None})

    payload = sent.get("payload")
    assert payload is not None
    # strip header
    body = payload.split(b"\r\n\r\n", 1)[1]
    req = json.loads(body.decode("utf-8"))
    assert req["params"]["rootUri"] == "file:///tmp/ws"


def test_no_inject_when_rooturi_present(monkeypatch):
    msg = json.dumps(_make_init({"rootUri": "file:///already"})).encode("utf-8")
    sent = {}

    class FakeSock:
        def sendall(self, b):
            sent["payload"] = b

    def _read_mcp_message(_):
        return msg, "framed"

    monkeypatch.setattr(proxy, "_read_mcp_message", _read_mcp_message)
    def _stop(*args, **kwargs):
        raise SystemExit()
    monkeypatch.setattr(proxy, "_read_mcp_message", lambda _: _read_mcp_message(_) if not sent else (_stop()))
    with pytest.raises(SystemExit):
        proxy.forward_stdin_to_socket(FakeSock(), {"mode": None})
    body = sent["payload"].split(b"\r\n\r\n", 1)[1]
    req = json.loads(body.decode("utf-8"))
    assert req["params"]["rootUri"] == "file:///already"


def test_inject_rooturi_in_batch(monkeypatch):
    batch = [
        _make_init(),
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    msg = json.dumps(batch).encode("utf-8")
    sent = {}

    class FakeSock:
        def sendall(self, b):
            sent["payload"] = b

    def _read_mcp_message(_):
        return msg, "framed"

    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", "/tmp/ws2")
    monkeypatch.setattr(proxy, "_read_mcp_message", _read_mcp_message)
    def _stop(*args, **kwargs):
        raise SystemExit()
    monkeypatch.setattr(proxy, "_read_mcp_message", lambda _: _read_mcp_message(_) if not sent else (_stop()))
    with pytest.raises(SystemExit):
        proxy.forward_stdin_to_socket(FakeSock(), {"mode": None})
    body = sent["payload"].split(b"\r\n\r\n", 1)[1]
    req = json.loads(body.decode("utf-8"))
    assert req[0]["params"]["rootUri"] == "file:///tmp/ws2"
