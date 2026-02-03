import json
import http.client
import socket
from types import SimpleNamespace

import pytest

from app import http_server


class DummyDB:
    def __init__(self):
        self.fts_enabled = True
        self.search_calls = []
        self.repo_calls = []

    def search(self, q, repo, limit, snippet_max_lines):
        self.search_calls.append((q, repo, limit, snippet_max_lines))
        hit = SimpleNamespace(path="a.py", repo=repo, line=3, snippet="L3: hit")
        return [hit], {"returned": 1, "total": 1}

    def repo_candidates(self, q, limit):
        self.repo_calls.append((q, limit))
        return [{"repo": "r1", "score": 1.0}]


class DummyIndexer:
    def __init__(self):
        self.cfg = SimpleNamespace(snippet_max_lines=5)
        self.status = SimpleNamespace(
            index_ready=True,
            last_scan_ts=1.0,
            scanned_files=2,
            indexed_files=3,
            errors=0,
        )
        self.rescan_requested = False

    def request_rescan(self):
        self.rescan_requested = True

    def get_last_commit_ts(self):
        return 123

    def get_queue_depths(self):
        return {"watcher": 1, "db_writer": 2, "telemetry": 0}


def _request_json(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body.decode("utf-8"))


@pytest.mark.allow_socket
def test_http_server_endpoints(tmp_path):
    db = DummyDB()
    indexer = DummyIndexer()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    httpd, port = http_server.serve_forever("127.0.0.1", port, db, indexer, version="test")
    try:
        status, data = _request_json(port, "/health")
        assert status == 200
        assert data["ok"] is True

        status, data = _request_json(port, "/status")
        assert status == 200
        assert data["index_ready"] is True
        assert data["last_commit_ts"] == 123
        assert data["fts_enabled"] is True

        status, data = _request_json(port, "/search")
        assert status == 400
        assert data["ok"] is False

        status, data = _request_json(port, "/search?q=needle&limit=999")
        assert status == 200
        assert data["hits"][0]["snippet"] == "L3: hit"
        assert db.search_calls

        status, data = _request_json(port, "/repo-candidates")
        assert status == 400

        status, data = _request_json(port, "/repo-candidates?q=deckard")
        assert status == 200
        assert data["candidates"][0]["repo"] == "r1"

        status, data = _request_json(port, "/rescan")
        assert status == 200
        assert indexer.rescan_requested is True

        status, data = _request_json(port, "/missing")
        assert status == 404
        assert data["ok"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()


class DummyHTTPServer:
    calls = 0

    def __init__(self, addr, handler):
        DummyHTTPServer.calls += 1
        if DummyHTTPServer.calls == 1:
            raise OSError("bind failed")
        self.addr = addr
        self.handler = handler

    def serve_forever(self):
        return None

    def shutdown(self):
        return None


class DummyRegistry:
    def find_free_port(self, start_port):
        raise RuntimeError("no free ports")

    def register(self, workspace_root, port, pid):
        raise RuntimeError("register failed")


def test_serve_forever_fallback_and_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(http_server, "HTTPServer", DummyHTTPServer)
    import app.registry as registry

    monkeypatch.setattr(registry, "ServerRegistry", DummyRegistry, raising=True)

    db = DummyDB()
    indexer = DummyIndexer()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    occupied_port = sock.getsockname()[1]

    try:
        httpd, actual_port = http_server.serve_forever(
            "127.0.0.1",
            occupied_port,
            db,
            indexer,
            version="test",
            workspace_root=str(tmp_path),
        )
        assert actual_port != occupied_port
        httpd.shutdown()
    finally:
        sock.close()
