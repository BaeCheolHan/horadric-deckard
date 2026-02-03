import json
import sqlite3
import threading
import pytest

from mcp.tools import deckard_guide as sari_guide
from mcp.tools import repo_candidates as repo_candidates_tool
from mcp.tools import search_symbols as search_symbols_tool
from mcp.tools import search_api_endpoints as search_api_endpoints_tool
from mcp.tools import get_callers as get_callers_tool
from mcp.tools import get_implementations as get_impl_tool
from mcp.tools import rescan as rescan_tool
from mcp.tools import scan_once as scan_once_tool
from mcp.tools import index_file as index_file_tool
from mcp.tools.registry import build_default_registry


class DummyRepoDB:
    def repo_candidates(self, q, limit=3, root_ids=None):
        return [{"repo": "repo", "score": 2, "evidence": ""}]


class DummySymbolsDB:
    def search_symbols(self, query, limit=20, root_ids=None):
        return [{"repo": "repo", "path": "root-aaaa/a.py", "line": 1, "kind": "fn", "name": query}]


class DummyIndexer:
    def __init__(self, enabled=True, mode="leader"):
        self.indexing_enabled = enabled
        self.indexer_mode = mode
        self.status = type("S", (), {"scanned_files": 1, "indexed_files": 1})()
        self._events = []
        self._rescans = 0
        self._scans = 0

    def request_rescan(self):
        self._rescans += 1

    def scan_once(self):
        self._scans += 1

    def _process_watcher_event(self, evt):
        self._events.append(evt)


class DummyIndexerDecode(DummyIndexer):
    def _decode_db_path(self, _db_path):
        return ("root", "decoded.txt")


class SqliteDB:
    def __init__(self):
        self._read = sqlite3.connect(":memory:")
        self._read.row_factory = sqlite3.Row
        self._read_lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        cur = self._read.cursor()
        cur.execute("CREATE TABLE symbols (path TEXT, name TEXT, kind TEXT, line INTEGER, metadata TEXT, content TEXT)")
        cur.execute("CREATE TABLE symbol_relations (from_path TEXT, from_symbol TEXT, line INTEGER, rel_type TEXT, to_symbol TEXT)")
        self._read.commit()


def test_sari_guide_pack():
    res = sari_guide.execute_deckard_guide({})
    text = res["content"][0]["text"]
    assert text.startswith("PACK1 tool=sari_guide ok=true")


def test_repo_candidates_pack():
    res = repo_candidates_tool.execute_repo_candidates({"query": "q"}, DummyRepoDB(), None, [])
    text = res["content"][0]["text"]
    assert text.startswith("PACK1 tool=repo_candidates ok=true")


def test_search_symbols_pack():
    res = search_symbols_tool.execute_search_symbols({"query": "fn"}, DummySymbolsDB(), [])
    text = res["content"][0]["text"]
    assert text.startswith("PACK1 tool=search_symbols ok=true")


def test_search_api_endpoints_pack():
    db = SqliteDB()
    meta = json.dumps({"http_path": "/v1/test", "annotations": ["GET"]})
    db._read.execute(
        "INSERT INTO symbols (path, name, kind, line, metadata, content) VALUES (?,?,?,?,?,?)",
        ("root-aaaa/a.py", "handler", "function", 1, meta, "def handler(): pass"),
    )
    db._read.commit()
    res = search_api_endpoints_tool.execute_search_api_endpoints({"path": "/v1"}, db, [])
    text = res["content"][0]["text"]
    assert "PACK1 tool=search_api_endpoints ok=true" in text


def test_get_callers_and_implementations_pack():
    db = SqliteDB()
    db._read.execute(
        "INSERT INTO symbol_relations (from_path, from_symbol, line, rel_type, to_symbol) VALUES (?,?,?,?,?)",
        ("root-aaaa/a.py", "caller", 2, "call", "target"),
    )
    db._read.commit()
    res = get_callers_tool.execute_get_callers({"name": "target"}, db, [])
    text = res["content"][0]["text"]
    assert "PACK1 tool=get_callers ok=true" in text

    res = get_impl_tool.execute_get_implementations({"name": "target"}, db, [])
    text = res["content"][0]["text"]
    assert "PACK1 tool=get_implementations ok=true" in text


def test_rescan_scan_once_and_index_file():
    indexer = DummyIndexer()
    res = rescan_tool.execute_rescan({}, indexer)
    assert "PACK1 tool=rescan ok=true" in res["content"][0]["text"]

    res = scan_once_tool.execute_scan_once({}, indexer)
    assert "PACK1 tool=scan_once ok=true" in res["content"][0]["text"]

    res = index_file_tool.execute_index_file({"path": "./file.txt"}, indexer, ["."])
    assert "PACK1 tool=index_file ok=true" in res["content"][0]["text"]


def test_rescan_and_scan_once_errors():
    res = rescan_tool.execute_rescan({}, None)
    assert "ok=false" in res["content"][0]["text"]

    bad_indexer = DummyIndexer(enabled=False, mode="off")
    res = scan_once_tool.execute_scan_once({}, bad_indexer)
    assert "ERR_INDEXER_DISABLED" in res["content"][0]["text"]


def test_index_file_errors(tmp_path):
    bad_indexer = DummyIndexer(enabled=False, mode="follower")
    res = index_file_tool.execute_index_file({"path": "x.txt"}, bad_indexer, [str(tmp_path)])
    assert "ERR_INDEXER_FOLLOWER" in res["content"][0]["text"]

    res = index_file_tool.execute_index_file({"path": str(tmp_path / "x.txt")}, DummyIndexer(), [str(tmp_path / "other")])
    assert "ERR_ROOT_OUT_OF_SCOPE" in res["content"][0]["text"]

    res = index_file_tool.execute_index_file({"path": str(tmp_path / "x.txt")}, DummyIndexerDecode(), [str(tmp_path)])
    assert "requested=true" in res["content"][0]["text"]


def test_invalid_args_for_tools():
    res = repo_candidates_tool.execute_repo_candidates({}, DummyRepoDB(), None, [])
    assert "INVALID_ARGS" in res["content"][0]["text"]

    res = search_symbols_tool.execute_search_symbols({}, DummySymbolsDB(), [])
    assert "PACK1 tool=search_symbols" in res["content"][0]["text"]

    res = get_callers_tool.execute_get_callers({}, SqliteDB(), [])
    assert "INVALID_ARGS" in res["content"][0]["text"]

    res = get_impl_tool.execute_get_implementations({}, SqliteDB(), [])
    assert "INVALID_ARGS" in res["content"][0]["text"]

    res = search_api_endpoints_tool.execute_search_api_endpoints({}, SqliteDB(), [])
    assert "INVALID_ARGS" in res["content"][0]["text"]


def test_registry_contains_search():
    registry = build_default_registry()
    names = {t["name"] for t in registry.list_tools()}
    assert "search" in names


def test_registry_execute_unknown():
    registry = build_default_registry()
    with pytest.raises(ValueError):
        registry.execute("missing", None, {})
