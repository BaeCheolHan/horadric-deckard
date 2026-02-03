import json
import os
import types

import pytest

import mcp.tools._util as util
import mcp.tools.list_files as list_files_tool
import mcp.tools.search_symbols as search_symbols_tool
import mcp.tools.search as search_tool
import mcp.tools.status as status_tool
import mcp.tools.repo_candidates as repo_candidates_tool
import mcp.tools.read_file as read_file_tool
import mcp.tools.read_symbol as read_symbol_tool
import mcp.tools.rescan as rescan_tool
import mcp.tools.scan_once as scan_once_tool
import mcp.tools.index_file as index_file_tool
import mcp.tools.search_api_endpoints as search_api_endpoints_tool
import mcp.tools.get_callers as get_callers_tool
import mcp.tools.get_implementations as get_implementations_tool
import mcp.tools.deckard_guide as deckard_guide_tool


class DummyLogger:
    def __init__(self):
        self.lines = []

    def log_telemetry(self, line):
        self.lines.append(line)

    def log_info(self, line):
        self.lines.append(line)

    def log_error(self, line):
        self.lines.append(line)


class DummyDB:
    def __init__(self):
        self.fts_enabled = True

    def get_repo_stats(self, *args, **kwargs):
        return {"repo1": 2, "repo2": 1}

    def list_files(self, **kwargs):
        files = [{"path": "a.py"}, {"path": "b.py"}]
        meta = {"total": 3}
        return files, meta

    def search_symbols(self, query, limit=20, **kwargs):
        return [
            {"repo": "r", "path": "a.py", "line": 10, "kind": "function", "name": "f"},
        ] * max(1, limit)

    def get_index_status(self):
        return {"total_files": 10}

    def search_v2(self, opts):
        hit = types.SimpleNamespace(
            repo="r",
            path="a.py",
            score=1.0,
            hit_reason="reason",
            snippet="L12: hello\nworld",
            mtime=1,
            size=2,
            match_count=1,
            file_type="py",
            context_symbol="f",
            docstring="doc\nline2\nline3\nline4",
        )
        meta = {"total": 2, "total_mode": "exact", "fallback_used": False, "total_scanned": 10}
        return [hit, hit], meta

    def repo_candidates(self, q, limit=3, **kwargs):
        return [{"repo": "r1", "score": 12}, {"repo": "r2", "score": 6}, {"repo": "r3", "score": 3}][:limit]

    def read_file(self, path):
        if "missing" in path:
            return None
        return "content"

    def get_symbol_block(self, path, name):
        if name == "missing":
            return None
        return {
            "name": name,
            "start_line": 1,
            "end_line": 2,
            "content": "def x():\n  pass",
            "docstring": "doc",
            "metadata": json.dumps({"annotations": ["a"], "http_path": "/v1/x"}),
        }


class DummyLock:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


class DummyRead:
    def __init__(self, rows):
        self._rows = rows
    def execute(self, _sql, _params):
        return types.SimpleNamespace(fetchall=lambda: self._rows)


def test_pack_utilities(monkeypatch):
    assert util.pack_encode_text("a b") == "a%20b"
    assert util.pack_encode_id("a/b") == "a/b"
    assert util.pack_header("t", {"k": "v"}, returned=1, total=2, total_mode="exact").startswith("PACK1 tool=t ok=true")
    assert util.pack_header("t", {}, total_mode="none").startswith("PACK1 tool=t ok=true")
    assert util.pack_line("p", single_value="x") == "p:x"
    assert util.pack_line("m", kv={"a": "1"}) == "m:a=1"
    assert util.pack_line("x") == "x:"
    err = util.pack_error("tool", util.ErrorCode.INVALID_ARGS, "bad", hints=["h"], trace="t")
    assert "ok=false" in err
    assert "code=INVALID_ARGS" in err
    assert util.pack_truncated(10, 2, "true") == "m:truncated=true next=use_offset offset=10 limit=2"

    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    out = util.mcp_response("t", lambda: "PACK1 tool=t ok=true", lambda: {"ok": True})
    assert "PACK1 tool=t ok=true" in out["content"][0]["text"]

    monkeypatch.setenv("DECKARD_FORMAT", "json")
    monkeypatch.setenv("DECKARD_RESPONSE_COMPACT", "0")
    out = util.mcp_response("t", lambda: "bad", lambda: {"ok": True})
    assert "\"ok\": true" in out["content"][0]["text"]

    out = util.mcp_json({"ok": True})
    assert "\"ok\": true" in out["content"][0]["text"]

    def bad_json():
        raise RuntimeError("x")
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    out = util.mcp_response("t", lambda: "bad", bad_json)
    assert out.get("isError") is True

    def boom():
        raise RuntimeError("x")
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    out = util.mcp_response("t", boom, lambda: {"ok": True})
    assert out.get("isError") is True


def test_list_files_pack_and_json(monkeypatch):
    db = DummyDB()
    logger = DummyLogger()
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = list_files_tool.execute_list_files({"limit": 2}, db, logger, [])
    assert "PACK1 tool=list_files ok=true" in res["content"][0]["text"]

    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = list_files_tool.execute_list_files({"repo": "r", "offset": "bad", "limit": "bad"}, db, logger, [])
    text = res["content"][0]["text"]
    assert "\"files\"" in text

    res = list_files_tool.execute_list_files({}, db, logger, [])
    assert "\"repos\"" in res["content"][0]["text"]


def test_search_symbols_pack_and_json(monkeypatch):
    db = DummyDB()
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = search_symbols_tool.execute_search_symbols({"query": "x", "limit": 50}, db, [])
    assert "PACK1 tool=search_symbols ok=true" in res["content"][0]["text"]

    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = search_symbols_tool.execute_search_symbols({"query": "x"}, db, [])
    assert "\"symbols\"" in res["content"][0]["text"]


def test_search_pack_and_json(monkeypatch):
    db = DummyDB()
    logger = DummyLogger()
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = search_tool.execute_search({"query": "q", "limit": 2, "type": "docs", "scope": "workspace"}, db, logger, [])
    assert "PACK1 tool=search ok=true" in res["content"][0]["text"]

    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = search_tool.execute_search({"query": "q", "limit": "bad", "offset": "bad", "context_lines": "bad"}, db, logger, [])
    assert "\"results\"" in res["content"][0]["text"]

    res = search_tool.execute_search({"query": ""}, db, logger, [])
    assert res.get("isError") is True


def test_search_json_branches(monkeypatch):
    class DBApprox(DummyDB):
        def get_index_status(self):
            return {"total_files": 200000}
        def get_repo_stats(self):
            return {str(i): i for i in range(60)}
        def search_v2(self, opts):
            return [], {"total": -1, "total_mode": "approx", "fallback_used": True, "total_scanned": 0}

    db = DBApprox()
    logger = DummyLogger()
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = search_tool.execute_search({"query": "q", "exclude_patterns": ["x"], "path_pattern": "p"}, db, logger, [])
    text = res["content"][0]["text"]
    assert "\"approx_total\"" in text
    assert "\"hints\"" in text


def test_search_pack_truncation(monkeypatch):
    class DBPack(DummyDB):
        def search_v2(self, opts):
            hit = types.SimpleNamespace(
                repo="r",
                path="a.py",
                score=1.0,
                hit_reason="reason",
                snippet="L5: x",
            )
            return [hit] * 20, {"total": -1, "total_mode": "approx", "fallback_used": False}

    db = DBPack()
    logger = DummyLogger()
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = search_tool.execute_search({"query": "q", "limit": 50, "repo": "r"}, db, logger, [])
    text = res["content"][0]["text"]
    assert "m:truncated=maybe" in text


def test_search_json_has_more_filtered(monkeypatch):
    class DBMore(DummyDB):
        def search_v2(self, opts):
            hit = types.SimpleNamespace(
                repo="r",
                path="a.py",
                score=1.0,
                hit_reason="reason",
                snippet="L1: x",
            )
            return [hit], {"total": 100, "total_mode": "exact", "fallback_used": False}

    db = DBMore()
    logger = DummyLogger()
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = search_tool.execute_search({"query": "q", "limit": 1, "exclude_patterns": ["x"]}, db, logger, [])
    text = res["content"][0]["text"]
    assert "\"warnings\"" in text
    assert "\"filtered_total\"" in text


def test_search_total_mode_hint_path_pattern(monkeypatch):
    seen = {}

    class DBMid(DummyDB):
        def get_index_status(self):
            return {"total_files": 60000}
        def get_repo_stats(self):
            return {str(i): i for i in range(30)}
        def search_v2(self, opts):
            seen["mode"] = opts.total_mode
            return [], {"total": 0, "total_mode": opts.total_mode, "fallback_used": False}

    class DummyOpts:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(search_tool, "SearchOptions", DummyOpts)
    db = DBMid()
    logger = DummyLogger()
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    search_tool.execute_search({"query": "q", "path_pattern": "src/*"}, db, logger, [])
    assert seen["mode"] == "approx"


def test_status_pack_and_json(monkeypatch):
    class DummyIndexer:
        def __init__(self):
            self.status = types.SimpleNamespace(
                index_ready=True,
                last_scan_ts=1,
                scanned_files=2,
                indexed_files=3,
                errors=0,
            )
        def get_last_commit_ts(self):
            return 4
        def get_queue_depths(self):
            return {"watcher": 1, "db_writer": 2, "telemetry": 3}

    class DummyCfg:
        include_ext = ["py"]
        exclude_dirs = ["x"]
        exclude_globs = []
        max_file_bytes = 10

    db = DummyDB()
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = status_tool.execute_status({"details": True}, DummyIndexer(), db, DummyCfg(), "/tmp", "1.0", logger=DummyLogger())
    assert "PACK1 tool=status ok=true" in res["content"][0]["text"]

    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = status_tool.execute_status({}, DummyIndexer(), db, DummyCfg(), "/tmp", "1.0")
    assert "\"index_ready\"" in res["content"][0]["text"]


def test_repo_candidates_pack_and_json(monkeypatch):
    db = DummyDB()
    logger = DummyLogger()
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = repo_candidates_tool.execute_repo_candidates({"query": "q", "limit": 2}, db, logger, [])
    assert "PACK1 tool=repo_candidates ok=true" in res["content"][0]["text"]

    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = repo_candidates_tool.execute_repo_candidates({"query": "q", "limit": 1}, db, logger, [])
    assert "\"candidates\"" in res["content"][0]["text"]

    res = repo_candidates_tool.execute_repo_candidates({"query": ""}, db, logger, [])
    assert res.get("isError") is True

    res = repo_candidates_tool.execute_repo_candidates({"query": "q", "limit": "bad"}, db, logger, [])
    assert "\"repo\"" in res["content"][0]["text"]


def test_read_file_and_symbol(monkeypatch):
    db = DummyDB()
    roots = [os.getcwd()]
    res = read_file_tool.execute_read_file({}, db, roots)
    assert "Error" in res["content"][0]["text"]
    res = read_file_tool.execute_read_file({"path": "missing"}, db, roots)
    assert "not found" in res["content"][0]["text"] or "out of scope" in res["content"][0]["text"]
    res = read_file_tool.execute_read_file({"path": "ok"}, db, roots)
    assert "content" in res["content"][0]["text"]

    logger = DummyLogger()
    res = read_symbol_tool.execute_read_symbol({"path": "p"}, db, logger, roots)
    assert res.get("isError") is True
    res = read_symbol_tool.execute_read_symbol({"path": "p", "name": "missing"}, db, logger, roots)
    assert res.get("isError") is True
    res = read_symbol_tool.execute_read_symbol({"path": "p", "name": "x"}, db, logger, roots)
    assert "Symbol" in res["content"][0]["text"]

    class BadDB(DummyDB):
        def get_symbol_block(self, path, name):
            return {
                "name": name,
                "start_line": 1,
                "end_line": 2,
                "content": "c",
                "docstring": "",
                "metadata": "bad-json",
            }

    res = read_symbol_tool.execute_read_symbol({"path": "p", "name": "x"}, BadDB(), logger, roots)
    assert "File:" in res["content"][0]["text"]


def test_rescan_and_scan_once(monkeypatch):
    class DummyIndexer:
        def __init__(self):
            self.called = False
            self.status = types.SimpleNamespace(scanned_files=1, indexed_files=2)
        def request_rescan(self):
            self.called = True
        def scan_once(self):
            self.called = True

    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = rescan_tool.execute_rescan({}, DummyIndexer())
    assert "PACK1 tool=rescan ok=true" in res["content"][0]["text"]

    res = scan_once_tool.execute_scan_once({}, DummyIndexer())
    assert "PACK1 tool=scan_once ok=true" in res["content"][0]["text"]

    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = rescan_tool.execute_rescan({}, DummyIndexer())
    assert "\"requested\"" in res["content"][0]["text"]
    res = scan_once_tool.execute_scan_once({}, DummyIndexer())
    assert "\"scanned_files\"" in res["content"][0]["text"]

    res = rescan_tool.execute_rescan({}, None)
    assert res.get("isError") is True
    res = scan_once_tool.execute_scan_once({}, None)
    assert res.get("isError") is True

    class BadIndexer(DummyIndexer):
        def __init__(self):
            self.called = False
        @property
        def status(self):
            raise RuntimeError("boom")

    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    res = scan_once_tool.execute_scan_once({}, BadIndexer())
    assert "PACK1 tool=scan_once ok=true" in res["content"][0]["text"]


def test_index_file_paths(monkeypatch):
    res = index_file_tool.execute_index_file({"path": ""}, None, [])
    assert res.get("isError") is True

    res = index_file_tool.execute_index_file({"path": "x"}, None, [])
    assert res.get("isError") is True

    called = {"n": 0}
    class DummyIndexer:
        def _process_watcher_event(self, evt):
            called["n"] += 1

    class DummyEvt:
        def __init__(self, kind, path, dest_path, ts):
            self.kind = kind
            self.path = path

    class DummyKind:
        MODIFIED = "mod"

    monkeypatch.setattr(index_file_tool, "FsEvent", DummyEvt)
    monkeypatch.setattr(index_file_tool, "FsEventKind", DummyKind)
    res = index_file_tool.execute_index_file({"path": "x"}, DummyIndexer(), [os.getcwd()])
    assert res.get("isError") is True or "PACK1" in res["content"][0]["text"]
    assert called["n"] == 1

    class BadIndexer:
        def _process_watcher_event(self, _evt):
            raise RuntimeError("boom")
    res = index_file_tool.execute_index_file({"path": "x"}, BadIndexer(), [os.getcwd()])
    assert res.get("isError") is True


def test_search_api_endpoints_and_relations(monkeypatch):
    rows = [
        {
            "path": "p",
            "name": "n",
            "kind": "method",
            "line": 1,
            "metadata": json.dumps({"http_path": "/v1/x", "annotations": ["a"]}),
            "content": "c",
            "from_path": "p",
            "from_symbol": "s",
            "rel_type": "implements",
        },
        {
            "path": "p2",
            "name": "n2",
            "kind": "method",
            "line": 2,
            "metadata": "not-json",
            "content": "c2",
            "from_path": "p2",
            "from_symbol": "s2",
            "rel_type": "calls",
        },
    ]
    db = types.SimpleNamespace(_read_lock=DummyLock(), _read=DummyRead(rows))

    res = search_api_endpoints_tool.execute_search_api_endpoints({"path": "/v1"}, db, [os.getcwd()])
    assert "results" in res["content"][0]["text"]

    res = search_api_endpoints_tool.execute_search_api_endpoints({"path": ""}, db, [os.getcwd()])
    assert "error" in res["content"][0]["text"]

    res = get_callers_tool.execute_get_callers({"name": "T"}, db, [os.getcwd()])
    assert "results" in res["content"][0]["text"]

    res = get_callers_tool.execute_get_callers({"name": ""}, db, [os.getcwd()])
    assert "error" in res["content"][0]["text"]

    res = get_implementations_tool.execute_get_implementations({"name": "T"}, db, [os.getcwd()])
    assert "results" in res["content"][0]["text"]

    res = get_implementations_tool.execute_get_implementations({"name": ""}, db, [os.getcwd()])
    assert "error" in res["content"][0]["text"]


def test_deckard_guide():
    res = deckard_guide_tool.execute_deckard_guide({})
    assert "Deckard" in res["content"][0]["text"]


def test_import_fallback_paths(monkeypatch, tmp_path):
    import builtins
    import importlib.util
    import sys

    def run_with_one_import_error(path, module_name, target_name):
        orig_import = builtins.__import__
        state = {"raised": False}

        def fake_import(name, *args, **kwargs):
            if name == target_name and not state["raised"]:
                state["raised"] = True
                raise ImportError("boom")
            return orig_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    base = os.path.join(os.path.dirname(__file__), "..", "..", "mcp", "tools")
    run_with_one_import_error(os.path.join(base, "list_files.py"), "list_files_fallback", "app.db")
    run_with_one_import_error(os.path.join(base, "search.py"), "search_fallback", "app.db")
    run_with_one_import_error(os.path.join(base, "status.py"), "status_fallback", "app.db")
    run_with_one_import_error(os.path.join(base, "repo_candidates.py"), "repo_candidates_fallback", "app.db")
    run_with_one_import_error(os.path.join(base, "read_symbol.py"), "read_symbol_fallback", "app.db")
    run_with_one_import_error(os.path.join(base, "rescan.py"), "rescan_fallback", "app.indexer")
    run_with_one_import_error(os.path.join(base, "scan_once.py"), "scan_once_fallback", "app.indexer")
    run_with_one_import_error(os.path.join(base, "index_file.py"), "index_file_fallback", "app.queue_pipeline")

    sys.modules["_util"] = util
    for name in ["get_callers.py", "get_implementations.py", "search_api_endpoints.py"]:
        path = os.path.join(base, name)
        spec = importlib.util.spec_from_file_location(name.replace(".py", "_fallback"), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
