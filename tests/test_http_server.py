import json
import http.client
from types import SimpleNamespace

from app.http_server import serve_forever
from app.models import SearchHit, SearchOptions
from app.engine_runtime import EngineMeta
import socket


class DummyDB:
    fts_enabled = True

    def __init__(self):
        self.engine = None

    def has_legacy_paths(self):
        return False

    def search_v2(self, opts: SearchOptions):
        hit = SearchHit(
            repo="repo",
            path="root-aaaa/file.txt",
            score=1.0,
            snippet="match",
            mtime=0,
            size=1,
            match_count=1,
            file_type="txt",
        )
        return [hit], {"total": 1, "total_mode": opts.total_mode}

    def repo_candidates(self, q, limit, root_ids=None):
        return [{"repo": "repo", "score": 1, "evidence": ""}]


class DummyDBLegacy(DummyDB):
    def has_legacy_paths(self):
        return True

class DummyIndexer:
    def __init__(self, root):
        self.cfg = SimpleNamespace(snippet_max_lines=5, workspace_roots=[root])
        self.status = SimpleNamespace(index_ready=True, last_scan_ts=0, scanned_files=1, indexed_files=1, errors=0)

    def get_last_commit_ts(self):
        return 0

    def get_queue_depths(self):
        return {"watcher": 0, "db_writer": 0, "telemetry": 0}

    def request_rescan(self):
        self._rescan = True


def _request(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", path)
    res = conn.getresponse()
    body = res.read().decode("utf-8")
    conn.close()
    return res.status, body


def test_http_server_health_and_search(tmp_path):
    db = DummyDB()
    indexer = DummyIndexer(str(tmp_path))
    httpd, actual_port = serve_forever("127.0.0.1", 0, db, indexer, version="1.0", workspace_root=str(tmp_path))
    try:
        status, body = _request(actual_port, "/health")
        assert status == 200
        assert json.loads(body)["ok"] is True

        status, body = _request(actual_port, "/search?q=hello")
        assert status == 200
        payload = json.loads(body)
        assert payload["ok"] is True
        assert payload["hits"]

        status, body = _request(actual_port, "/search")
        assert status == 400

        status, body = _request(actual_port, "/search?q=hello&root_ids=root-bad")
        assert status == 400

        status, body = _request(actual_port, "/status")
        assert status == 200
        assert json.loads(body)["ok"] is True

        status, body = _request(actual_port, "/repo-candidates?q=test")
        assert status == 200

        status, body = _request(actual_port, "/rescan")
        assert status == 200
    finally:
        httpd.shutdown()


def test_http_server_root_ids_legacy(tmp_path):
    db = DummyDBLegacy()
    indexer = DummyIndexer(str(tmp_path))
    httpd, actual_port = serve_forever("127.0.0.1", 0, db, indexer, version="1.0", workspace_root=str(tmp_path))
    try:
        status, _body = _request(actual_port, "/search?q=hello&root_ids=root-bad")
        assert status == 200
        status, _body = _request(actual_port, "/repo-candidates")
        assert status == 400
    finally:
        httpd.shutdown()


def test_http_server_port_conflict(monkeypatch, tmp_path):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    db = DummyDB()
    indexer = DummyIndexer(str(tmp_path))
    monkeypatch.setenv("DECKARD_HTTP_API_PORT_STRATEGY", "auto")
    httpd, actual_port = serve_forever("127.0.0.1", port, db, indexer, version="1.0", workspace_root=str(tmp_path))
    try:
        assert actual_port != port
    finally:
        httpd.shutdown()
        sock.close()


def test_http_server_port_conflict_strict(monkeypatch, tmp_path):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    db = DummyDB()
    indexer = DummyIndexer(str(tmp_path))
    monkeypatch.setenv("DECKARD_HTTP_API_PORT_STRATEGY", "strict")
    try:
        try:
            serve_forever("127.0.0.1", port, db, indexer, version="1.0", workspace_root=str(tmp_path))
        except RuntimeError:
            pass
    finally:
        sock.close()


def test_http_server_engine_unavailable(tmp_path):
    class EngineUnavailable:
        def status(self):
            return EngineMeta(
                engine_mode="embedded",
                engine_ready=False,
                engine_version="unknown",
                index_version="",
                reason="NOT_INSTALLED",
                hint="install",
            )

    db = DummyDB()
    db.engine = EngineUnavailable()
    indexer = DummyIndexer(str(tmp_path))
    httpd, actual_port = serve_forever("127.0.0.1", 0, db, indexer, version="1.0", workspace_root=str(tmp_path))
    try:
        status, body = _request(actual_port, "/search?q=hello")
        assert status == 503
    finally:
        httpd.shutdown()
