import json
import os
from pathlib import Path

from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.core.indexer import Indexer
from sari.core.workspace import WorkspaceManager
from sari.core.models import SearchHit
from sari.mcp.tools.search import execute_search
from sari.mcp.tools.status import execute_status


class DummyLogger:
    def log_telemetry(self, _msg):
        pass


class DummyEngine:
    def status(self):
        class S:
            engine_mode = "sqlite"
            engine_ready = True
            engine_version = "1.0"
            index_version = "v1"
        return S()

    def search_v2(self, opts):
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


class DummyDB:
    fts_enabled = True
    engine = DummyEngine()

    def has_legacy_paths(self):
        return False

    def get_repo_stats(self, root_ids=None):
        return {"repo": 1}


class DummyIndexer:
    def __init__(self):
        self.status = type("S", (), {"index_ready": True, "last_scan_ts": 0, "scanned_files": 1, "indexed_files": 1, "errors": 0})()
        self.indexer_mode = "leader"

    def get_last_commit_ts(self):
        return 0

    def get_queue_depths(self):
        return {"watcher": 0, "db_writer": 0, "telemetry": 0}


def test_search_contract_pack(tmp_path):
    res = execute_search({"query": "hello", "limit": 5, "total_mode": "approx"}, DummyDB(), DummyLogger(), [str(tmp_path)], engine=DummyEngine())
    text = res["content"][0]["text"]
    assert text.startswith("PACK1 tool=search ok=true")
    assert "m:total_mode=approx" in text
    assert "m:engine=sqlite" in text


def test_search_contract_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SARI_FORMAT", "json")
    res = execute_search({"query": "hello"}, DummyDB(), DummyLogger(), [str(tmp_path)], engine=DummyEngine())
    assert res["meta"]["engine"] == "sqlite"
    monkeypatch.delenv("SARI_FORMAT", raising=False)


def test_status_contract_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SARI_FORMAT", "json")
    res = execute_status({"details": True}, DummyIndexer(), DummyDB(), None, str(tmp_path), "1.0")
    assert "http_api_port" in res
    assert "http_api_port_config" in res
    assert "engine_mode" in res
    monkeypatch.delenv("SARI_FORMAT", raising=False)


def test_config_migration_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    ssot = tmp_path / ".config" / "sari" / "config.json"
    ssot.parent.mkdir(parents=True)
    ssot.write_text(json.dumps({"roots": ["/ssot"]}), encoding="utf-8")

    legacy_dir = workspace_root / ".codex" / "tools" / "SARI" / "config"
    legacy_dir.mkdir(parents=True)
    legacy = legacy_dir / "config.json"
    legacy.write_text(json.dumps({"roots": ["/legacy"]}), encoding="utf-8")

    resolved = WorkspaceManager.resolve_config_path(str(workspace_root))
    assert Path(resolved) == ssot
    assert json.loads(ssot.read_text(encoding="utf-8"))["roots"] == ["/ssot"]


def _make_cfg(tmp_path, include_ext, max_bytes):
    return Config(
        workspace_root=str(tmp_path),
        workspace_roots=[str(tmp_path)],
        server_host="127.0.0.1",
        server_port=47777,
        scan_interval_seconds=0,
        snippet_max_lines=5,
        max_file_bytes=max_bytes,
        db_path=str(tmp_path / "index.db"),
        include_ext=include_ext,
        include_files=[],
        exclude_dirs=[],
        exclude_globs=[],
        redact_enabled=False,
        commit_batch_size=10,
        http_api_host="127.0.0.1",
        http_api_port=7331,
    )


def test_include_ext_empty_allows(tmp_path):
    cfg = _make_cfg(tmp_path, include_ext=[], max_bytes=0)
    db = LocalSearchDB(cfg.db_path)
    indexer = Indexer(cfg, db, logger=None)
    file_path = Path(tmp_path) / "a.txt"
    file_path.write_text("hello", encoding="utf-8")
    st = file_path.stat()
    row = indexer._process_file_task(Path(tmp_path), file_path, st, 0, 0.0, False)
    assert row is not None


def test_include_ext_blocks(tmp_path):
    cfg = _make_cfg(tmp_path, include_ext=[".py"], max_bytes=0)
    db = LocalSearchDB(cfg.db_path)
    indexer = Indexer(cfg, db, logger=None)
    file_path = Path(tmp_path) / "a.txt"
    file_path.write_text("hello", encoding="utf-8")
    st = file_path.stat()
    row = indexer._process_file_task(Path(tmp_path), file_path, st, 0, 0.0, False)
    assert row is None


def test_max_file_bytes_skips_parse(tmp_path):
    cfg = _make_cfg(tmp_path, include_ext=[], max_bytes=1)
    db = LocalSearchDB(cfg.db_path)
    indexer = Indexer(cfg, db, logger=None)
    file_path = Path(tmp_path) / "a.txt"
    file_path.write_text("hello", encoding="utf-8")
    st = file_path.stat()
    row = indexer._process_file_task(Path(tmp_path), file_path, st, 0, 0.0, False)
    assert row is not None
    assert row.get("parse_status") == "skipped"
    assert row.get("parse_reason") == "too_large"