import pytest
from sari.core.search_engine import SearchEngine
from sari.core.models import SearchOptions

pytestmark = pytest.mark.gate


def _build_engine():
    engine = SearchEngine.__new__(SearchEngine)
    engine.db = type("DummyDB", (), {"settings": None})()
    engine._snippet_cache = {}
    engine._snippet_lru = []
    return engine


def test_process_sqlite_rows_handles_legacy_shape():
    engine = _build_engine()
    rows = [("root-1/a.py", "root-1", "repo1", 100, 12, "hello world")]
    hits = SearchEngine._process_sqlite_rows(engine, rows, SearchOptions(query="hello"))
    assert len(hits) == 1
    assert hits[0].repo == "repo1"
    assert hits[0].mtime == 100
    assert hits[0].size == 12


def test_process_sqlite_rows_handles_fts_shape():
    engine = _build_engine()
    rows = [("root-1/a.py", "a.py", "root-1", "repo1", 100, 12, "hello world")]
    hits = SearchEngine._process_sqlite_rows(engine, rows, SearchOptions(query="hello"))
    assert len(hits) == 1
    assert hits[0].repo == "repo1"
    assert hits[0].mtime == 100
    assert hits[0].size == 12
