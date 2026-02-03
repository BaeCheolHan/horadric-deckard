from app.engine_runtime import EngineMeta
from mcp.tools.status import execute_status


class DummyStatus:
    index_ready = True
    last_scan_ts = 1
    scanned_files = 2
    indexed_files = 2
    errors = 0


class DummyIndexer:
    def __init__(self):
        self.status = DummyStatus()
        self.indexer_mode = "leader"

    def get_last_commit_ts(self):
        return 2

    def get_queue_depths(self):
        return {"watcher": 1, "db_writer": 0, "telemetry": 0}


class DummyEngine:
    def status(self):
        return EngineMeta(
            engine_mode="embedded",
            engine_ready=False,
            engine_version="unknown",
            index_version="",
            reason="NOT_INSTALLED",
            hint="install",
            doc_count=0,
            index_size_bytes=0,
            last_build_ts=0,
            engine_mem_mb=512,
            index_mem_mb=256,
            engine_threads=2,
        )


class DummyDB:
    fts_enabled = True
    engine = DummyEngine()
    def get_repo_stats(self, root_ids=None):
        return {"repo": 2}


class DummyCfg:
    workspace_roots = []
    include_ext = []
    exclude_dirs = []
    exclude_globs = []
    max_file_bytes = 0
    http_api_port = 47777


def test_status_pack_includes_engine_meta(tmp_path):
    res = execute_status({}, DummyIndexer(), DummyDB(), DummyCfg(), str(tmp_path), "1.0")
    text = res["content"][0]["text"]
    assert text.startswith("PACK1 tool=status ok=true")
    assert "engine_mode" in text
    assert "engine_mem_mb" in text


def test_status_details_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = execute_status({"details": True}, DummyIndexer(), DummyDB(), DummyCfg(), str(tmp_path), "1.0")
    assert res.get("repo_stats") == {"repo": 2}
    monkeypatch.delenv("DECKARD_FORMAT", raising=False)


def test_status_no_db_no_indexer(tmp_path):
    res = execute_status({}, None, None, None, str(tmp_path), "1.0")
    text = res["content"][0]["text"]
    assert "index_ready" in text
