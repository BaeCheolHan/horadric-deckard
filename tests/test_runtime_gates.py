from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sari.mcp.server import LocalSearchMCPServer
from sari.core.config import Config
from sari.core.workspace import WorkspaceManager
from sari.core.db import LocalSearchDB

pytestmark = pytest.mark.gate


class _OneShotTransport:
    def __init__(self, *_args, **_kwargs):
        self.read_calls = 0

    def read_message(self):
        # First call ends the run loop cleanly.
        self.read_calls += 1
        return None

    def write_message(self, *_args, **_kwargs):
        return None


def test_mcp_server_run_initializes_transport_without_crash(monkeypatch):
    import sari.mcp.server as server_mod

    monkeypatch.setattr(server_mod, "McpTransport", _OneShotTransport)
    server = LocalSearchMCPServer("/tmp/ws")
    server.run()
    assert server.transport is not None
    server.shutdown()


def test_tantivy_dependency_is_pinned():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'tantivy==0.25.1' in text
    assert "tantivy>=" not in text


def test_tantivy_runtime_rejects_unsupported_version(monkeypatch, tmp_path):
    import sari.core.engine.tantivy_engine as te

    class FakeTantivy:
        __version__ = "0.20.0"

    monkeypatch.setattr(te, "tantivy", FakeTantivy)
    engine = te.TantivyEngine(str(tmp_path / "idx"), logger=MagicMock())
    assert engine._index is None
    assert "Unsupported tantivy version" in engine._disabled_reason


def test_tools_call_handles_missing_session_db():
    server = LocalSearchMCPServer("/tmp/ws")
    bad_session = MagicMock()
    bad_session.db = None
    bad_session.indexer = MagicMock()
    bad_session.config_data = {"workspace_roots": ["/tmp/ws"]}
    server.registry.get_or_create = MagicMock(return_value=bad_session)

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "status", "arguments": {}},
        }
    )

    assert "error" in response
    assert response["error"]["code"] == -32000
    assert "session.db is unavailable" in response["error"]["message"]
    server.shutdown()


def test_forward_to_daemon_reuses_single_connection(monkeypatch):
    import json as _json
    import sari.mcp.server as server_mod

    class FakeReader:
        def __init__(self):
            self.buf = b""
            self.pos = 0
            self.closed = False

        def push(self, payload: bytes):
            self.buf += payload

        def readline(self):
            if self.pos >= len(self.buf):
                return b""
            i = self.buf.find(b"\n", self.pos)
            if i < 0:
                out = self.buf[self.pos:]
                self.pos = len(self.buf)
                return out
            out = self.buf[self.pos : i + 1]
            self.pos = i + 1
            return out

        def read(self, n: int):
            out = self.buf[self.pos : self.pos + n]
            self.pos += len(out)
            return out

        def close(self):
            self.closed = True

    class FakeSocket:
        def __init__(self):
            self.reader = FakeReader()
            self.closed = False

        def makefile(self, _mode):
            return self.reader

        def sendall(self, _data: bytes):
            body = _json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            self.reader.push(header + body)

        def close(self):
            self.closed = True

    calls = {"count": 0}
    sock = FakeSocket()

    def _fake_connect(*_args, **_kwargs):
        calls["count"] += 1
        return sock

    monkeypatch.setattr(server_mod.socket, "create_connection", _fake_connect)

    server = LocalSearchMCPServer("/tmp/ws")
    server._proxy_to_daemon = True
    server._daemon_address = ("127.0.0.1", 47779)

    server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
    server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})

    assert calls["count"] == 1
    server.shutdown()
    assert sock.closed
    assert sock.reader.closed


def test_shutdown_closes_transport_and_logger():
    server = LocalSearchMCPServer("/tmp/ws")
    transport = MagicMock()
    logger = MagicMock()
    server.transport = transport
    server.logger = logger
    server.shutdown()
    transport.close.assert_called_once()
    logger.stop.assert_called_once()


def test_policy_uses_single_global_db_path():
    defaults = Config.get_defaults("/tmp/ws")
    assert defaults["db_path"] == str(WorkspaceManager.get_global_db_path())


def test_sqlite_busy_timeout_is_configured(tmp_path):
    db = LocalSearchDB(str(tmp_path / "gate.db"))
    row = db._read.execute("PRAGMA busy_timeout").fetchone()
    assert int(row[0]) >= 15000
    db.close_all()


def test_mcp_debug_log_redacts_sensitive_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("SARI_MCP_DEBUG_LOG", "1")
    monkeypatch.setenv("HOME", str(tmp_path))

    server = LocalSearchMCPServer("/tmp/ws")
    req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {
                "query": "hello",
                "api_key": "sk-live-secret",
                "content": "private source code payload",
            },
        },
    }
    server._log_debug_request("content-length", req)
    server.shutdown()

    log_path = tmp_path / ".local" / "share" / "sari" / "mcp_debug.log"
    text = log_path.read_text(encoding="utf-8")
    assert "sk-live-secret" not in text
    assert "private source code payload" not in text
    assert "[REDACTED]" in text
    assert "[REDACTED_TEXT" in text


def test_root_id_explicit_workspace_is_stable_for_nested_repos(tmp_path):
    parent = tmp_path / "parent"
    child = parent / "child"
    parent.mkdir(parents=True)
    child.mkdir(parents=True)
    (parent / ".sari").mkdir()

    legacy = WorkspaceManager.root_id(str(child))
    explicit = WorkspaceManager.root_id_for_workspace(str(child))

    # Legacy may lift to parent marker; explicit must bind to selected workspace.
    assert explicit == WorkspaceManager.root_id_for_workspace(str(child))
    assert explicit.startswith("root-")
    assert legacy.startswith("root-")
    assert legacy != explicit
