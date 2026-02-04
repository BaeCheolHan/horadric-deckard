from sari.core.models import SearchHit
from sari.core.engine_runtime import EngineMeta
from sari.mcp.tools.search import execute_search


class DummyDB:
    def __init__(self, legacy=False):
        self._legacy = legacy

    def has_legacy_paths(self):
        return self._legacy


class DummyEngine:
    def __init__(self):
        self.last_opts = None

    def status(self):
        return EngineMeta(
            engine_mode="sqlite",
            engine_ready=True,
            engine_version="1.0",
            index_version="v1",
        )

    def search_v2(self, opts):
        self.last_opts = opts
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


class DummyLogger:
    def log_telemetry(self, _msg):
        pass


class DummyEngineEmbedded(DummyEngine):
    def status(self):
        return EngineMeta(
            engine_mode="embedded",
            engine_ready=True,
            engine_version="1.0",
            index_version="v1",
        )


class DummyEngineTwo(DummyEngine):
    def search_v2(self, opts):
        hit1 = SearchHit(
            repo="repo",
            path="root-aaaa/file1.txt",
            score=1.0,
            snippet="match",
            mtime=0,
            size=1,
            match_count=1,
            file_type="txt",
        )
        hit2 = SearchHit(
            repo="repo",
            path="root-aaaa/file2.txt",
            score=0.5,
            snippet="match",
            mtime=0,
            size=1,
            match_count=1,
            file_type="txt",
        )
        return [hit1, hit2], {"total": 2, "total_mode": opts.total_mode}


def test_search_tool_pack_basic(tmp_path, monkeypatch):
    db = DummyDB()
    engine = DummyEngine()
    roots = [str(tmp_path)]
    args = {"query": "hello", "limit": 5}
    res = execute_search(args, db, DummyLogger(), roots, engine=engine)
    text = res["content"][0]["text"]
    assert text.startswith("PACK1 tool=search ok=true")
    assert "m:total=" in text
    assert "m:engine=sqlite" in text


def test_search_tool_root_ids_out_of_scope(tmp_path):
    db = DummyDB(legacy=False)
    engine = DummyEngine()
    roots = [str(tmp_path)]
    args = {"query": "hello", "root_ids": ["root-deadbeef"]}
    res = execute_search(args, db, DummyLogger(), roots, engine=engine)
    text = res["content"][0]["text"]
    assert "ok=false" in text
    assert "ERR_ROOT_OUT_OF_SCOPE" in text


def test_search_tool_json_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SARI_FORMAT", "json")
    db = DummyDB()
    engine = DummyEngineEmbedded()
    roots = [str(tmp_path)]
    res = execute_search({"query": "hello"}, db, DummyLogger(), roots, engine=engine)
    assert res.get("meta", {}).get("engine") == "embedded"
    monkeypatch.delenv("SARI_FORMAT", raising=False)


def test_search_tool_invalid_args(tmp_path):
    db = DummyDB()
    engine = DummyEngine()
    res = execute_search({}, db, DummyLogger(), [str(tmp_path)], engine=engine)
    text = res["content"][0]["text"]
    assert "INVALID_ARGS" in text


def test_search_tool_root_ids_legacy_allowed(tmp_path):
    db = DummyDB(legacy=True)
    engine = DummyEngine()
    res = execute_search({"query": "hello", "root_ids": ["root-bad"]}, db, DummyLogger(), [str(tmp_path)], engine=engine)
    text = res["content"][0]["text"]
    assert "ok=true" in text


def test_search_tool_truncated_pack(tmp_path):
    db = DummyDB()
    engine = DummyEngineTwo()
    res = execute_search({"query": "hello", "limit": 1}, db, DummyLogger(), [str(tmp_path)], engine=engine)
    text = res["content"][0]["text"]
    assert "truncated=maybe" in text