import io
import json
import threading

import pytest

from sari.mcp.server import LocalSearchMCPServer
from sari.mcp.transport import McpTransport

pytestmark = pytest.mark.gate


def _encode_framed(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_framed_output(raw: bytes) -> dict:
    head, body = raw.split(b"\r\n\r\n", 1)
    headers = {}
    for line in head.splitlines():
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get(b"content-length", b"0"))
    return json.loads(body[:length].decode("utf-8"))


def test_mcp_runloop_real_framed_io(monkeypatch):
    monkeypatch.setenv("SARI_STANDALONE_ONLY", "1")

    class NonClosingBytesIO(io.BytesIO):
        def close(self):
            # Keep buffer readable for assertion after server shutdown.
            pass

    req = {"jsonrpc": "2.0", "id": 11, "method": "ping", "params": {}}
    inp = io.BytesIO(_encode_framed(req))
    out = NonClosingBytesIO()

    server = LocalSearchMCPServer("/tmp/ws")
    server.transport = McpTransport(inp, out)
    server.run()

    raw = out.getvalue()
    assert b"Content-Length:" in raw
    response = _read_framed_output(raw)
    assert response["id"] == 11
    assert "result" in response


def test_daemon_forward_reuses_single_socket(monkeypatch):
    monkeypatch.setenv("SARI_STANDALONE_ONLY", "1")

    accepted = {"connections": 0, "requests": 0}
    class FakeReader:
        def __init__(self):
            self.buf = b""
            self.pos = 0

        def push(self, payload: bytes):
            self.buf += payload

        def readline(self):
            if self.pos >= len(self.buf):
                return b""
            idx = self.buf.find(b"\n", self.pos)
            if idx < 0:
                out = self.buf[self.pos :]
                self.pos = len(self.buf)
                return out
            out = self.buf[self.pos : idx + 1]
            self.pos = idx + 1
            return out

        def read(self, n: int):
            out = self.buf[self.pos : self.pos + n]
            self.pos += len(out)
            return out

        def close(self):
            return None

    class FakeSocket:
        def __init__(self):
            accepted["connections"] += 1
            self.reader = FakeReader()

        def makefile(self, _mode):
            return self.reader

        def sendall(self, payload: bytes):
            # Decode request and encode response using framed protocol.
            body = payload.split(b"\r\n\r\n", 1)[1]
            req = json.loads(body.decode("utf-8"))
            accepted["requests"] += 1
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
            self.reader.push(_encode_framed(resp))

        def close(self):
            return None

    sock = FakeSocket()
    monkeypatch.setattr("sari.mcp.server.socket.create_connection", lambda *_a, **_k: sock)

    server = LocalSearchMCPServer("/tmp/ws")
    server._proxy_to_daemon = True
    server._daemon_address = ("127.0.0.1", 47779)

    server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
    server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
    server.shutdown()

    assert accepted["connections"] == 1
    assert accepted["requests"] == 2
