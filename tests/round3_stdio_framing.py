import io
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server import LocalSearchMCPServer


def _run_server(input_bytes, tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_LOG_DIR", str(tmp_path / "logs"))

    server = LocalSearchMCPServer(str(tmp_path))
    fake_in = io.BytesIO(input_bytes)
    fake_out = io.BytesIO()

    class FakeIO:
        def __init__(self, buf):
            self.buffer = buf

    monkeypatch.setattr(sys, "stdin", FakeIO(fake_in))
    monkeypatch.setattr(sys, "stdout", FakeIO(fake_out))

    server.run()
    return fake_out.getvalue()


def _framed(payload):
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _parse_framed(output):
    head, body = output.split(b"\r\n\r\n", 1)
    clen = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            clen = int(line.split(b":", 1)[1].strip())
            break
    assert clen > 0
    return json.loads(body[:clen].decode("utf-8"))


def test_framed_initialize_response(tmp_path, monkeypatch):
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
            "rootUri": f"file://{tmp_path}",
        },
    }
    output = _run_server(_framed(req), tmp_path, monkeypatch)
    resp = _parse_framed(output)
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "deckard"


def test_jsonl_initialize_response(tmp_path, monkeypatch):
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
    }
    line = json.dumps(req).encode("utf-8") + b"\n"
    output = _run_server(line, tmp_path, monkeypatch)
    assert b"Content-Length" not in output
    resp = json.loads(output.decode("utf-8").strip())
    assert resp["id"] == 2


def test_parse_error_response(tmp_path, monkeypatch):
    bad = b"Content-Length: 5\r\n\r\n{bad}"
    output = _run_server(bad, tmp_path, monkeypatch)
    resp = _parse_framed(output)
    assert resp["error"]["code"] == -32700


def test_unknown_method_response(tmp_path, monkeypatch):
    req = {"jsonrpc": "2.0", "id": 99, "method": "nope"}
    output = _run_server(_framed(req), tmp_path, monkeypatch)
    resp = _parse_framed(output)
    assert resp["error"]["code"] == -32601
    assert resp["id"] == 99


def test_tools_list_response(tmp_path, monkeypatch):
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    output = _run_server(_framed(req), tmp_path, monkeypatch)
    resp = _parse_framed(output)
    tools = resp["result"]["tools"]
    assert any(t["name"] == "search" for t in tools)
