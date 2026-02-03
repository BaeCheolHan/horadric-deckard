import sqlite3
import time

from app.db import LocalSearchDB
from app.models import SearchOptions
from app.search_engine import SearchEngine


def _seed_db(tmp_path):
    db = LocalSearchDB(str(tmp_path / "s.db"))
    db.upsert_files([
        ("repo1/a.py", "repo1", int(time.time()), 10, "hello needle world", int(time.time())),
        ("repo2/b.py", "repo2", int(time.time()), 10, "needle extra", int(time.time())),
    ])
    db.upsert_symbols([
        ("repo1/a.py", "Foo", "class", 1, 1, "class Foo", "", "{}", ""),
    ])
    db.upsert_repo_meta("repo1", tags="tag1", domain="code", priority=2)
    return db


def test_search_v2_recency_boost_and_fts_error(tmp_path, monkeypatch):
    db = _seed_db(tmp_path)
    engine = SearchEngine(db)

    def fake_search_symbols(q, repo=None, limit=50):
        return [{
            "repo": "repo1",
            "path": "repo1/a.py",
            "snippet": "L1: class Foo",
            "mtime": int(time.time()),
            "size": 10,
            "kind": "class",
            "name": "Foo",
            "docstring": "",
            "metadata": "{}",
        }]

    monkeypatch.setattr(db, "search_symbols", fake_search_symbols)

    def fake_search_fts(*_args, **_kwargs):
        raise sqlite3.OperationalError("fts fail")

    monkeypatch.setattr(db, "_search_fts", fake_search_fts)
    monkeypatch.setattr(db, "_search_like", lambda *args, **kwargs: ([], {"total": 0, "total_mode": "exact"}))

    opts = SearchOptions(query="foo", limit=5, recency_boost=True, total_mode="exact")
    hits, meta = engine.search_v2(opts)
    assert hits
    assert hits[0].score > 1000

    db.close()


def test_search_like_slicing_and_total_mode(tmp_path):
    db = _seed_db(tmp_path)
    engine = SearchEngine(db)
    opts = SearchOptions(query="needle", limit=1, offset=1, total_mode="approx")
    hits, meta = engine._search_like(opts, ["needle"], {}, no_slice=False)
    assert len(hits) == 1
    assert meta["total"] == -1
    db.close()


def test_search_regex_repo_filter(tmp_path):
    db = _seed_db(tmp_path)
    engine = SearchEngine(db)
    opts = SearchOptions(query="needle", limit=1, offset=0, use_regex=True, recency_boost=True, repo="repo1")
    hits, meta = engine._search_regex(opts, ["needle"], {})
    assert meta.get("regex_mode") is True
    assert hits
    db.close()


def test_process_rows_meta_and_proximity(tmp_path):
    db = _seed_db(tmp_path)
    engine = SearchEngine(db)
    opts = SearchOptions(query="tag1 missing", limit=5, recency_boost=True)

    rows = [
        {
            "repo": "repo1",
            "path": "repo1/a.py",
            "mtime": int(time.time()),
            "size": 10,
            "score": 1.0,
            "content": None,
        }
    ]

    hits = engine._process_rows(rows, opts, ["tag1", "missing"])
    assert hits
    assert hits[0].hit_reason
    db.close()


def test_repo_candidates_like_fallback(tmp_path, monkeypatch):
    db = _seed_db(tmp_path)
    engine = SearchEngine(db)

    # Insert a raw content row to ensure LIKE matches without FTS.
    db._write.execute(
        "INSERT OR REPLACE INTO files(path, repo, mtime, size, content, last_seen) VALUES (?,?,?,?,?,?)",
        ("raw.txt", "repo_raw", int(time.time()), 10, "needle here", int(time.time())),
    )
    db._write.commit()

    orig_execute = db._read.execute

    def bad_execute(sql, params=()):
        if "files_fts" in sql:
            raise sqlite3.OperationalError("bad")
        return orig_execute(sql, params)

    if db.fts_enabled:
        class ConnWrapper:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, *args, **kwargs):
                return bad_execute(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        db._read = ConnWrapper(db._read)

    out = engine.repo_candidates("needle", limit=2)
    assert out
    db.close()
