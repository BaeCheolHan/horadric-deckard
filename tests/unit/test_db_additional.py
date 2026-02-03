import sqlite3

from app.db import LocalSearchDB, _decompress


def test_decompress_invalid_bytes():
    assert _decompress(b"not-zlib") == "b'not-zlib'"


def test_db_empty_upserts(tmp_path):
    db = LocalSearchDB(str(tmp_path / "t.db"))
    try:
        assert db.upsert_files([]) == 0
        assert db.upsert_symbols([]) == 0
        assert db.upsert_relations([]) == 0
        assert db.update_last_seen([], 1) == 0
        assert db.delete_files([]) == 0
    finally:
        db.close()


def test_db_symbols_padding_and_exact(tmp_path):
    db = LocalSearchDB(str(tmp_path / "t2.db"))
    try:
        db.upsert_files([("a.py", "__root__", 1, 1, "x", 1)])

        class SymbolContainer:
            symbols = [("a.py", "Foo", "class", 1, 1, "class Foo", "", "{}", "")]

        assert db.upsert_symbols(SymbolContainer()) == 1
        symbols = [
            ("a.py", "Foo", "class", 1, 1, "class Foo", "", "{}", ""),
            ("a.py", "Bar", "class", 2),
        ]
        count = db.upsert_symbols(symbols)
        assert count == 2
        assert db._is_exact_symbol("Foo") is True
        assert db.get_symbol_block("missing.py", "Nope") is None
    finally:
        db.close()


def test_db_update_last_seen_tx_empty(tmp_path):
    db = LocalSearchDB(str(tmp_path / "t3.db"))
    try:
        cur = db._write.cursor()
        assert db.update_last_seen_tx(cur, [], 1) == 0
        db.upsert_files([("a.py", "__root__", 1, 1, "x", 1)])
        assert db.update_last_seen_tx(cur, ["a.py"], 2) == 1
    finally:
        db.close()


def test_db_try_enable_fts_failure():
    class DummyConn:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("bad")

    db = LocalSearchDB(":memory:")
    try:
        assert db._try_enable_fts(DummyConn()) is False
    finally:
        db.close()


def test_db_stats_cache_and_repo_meta(tmp_path):
    db = LocalSearchDB(str(tmp_path / "t4.db"))
    try:
        stats = db.get_repo_stats()
        stats2 = db.get_repo_stats()
        assert stats2 == stats
        db.clear_stats_cache()
        db.upsert_repo_meta("repo1", tags="t", description="d", priority=1)
        meta = db.get_repo_meta("repo1")
        assert meta["repo_name"] == "repo1"
        db.delete_file("missing.txt")
        db.delete_files(["missing.txt"])

        class DummyConn:
            def close(self):
                raise RuntimeError("close")

        db._read = DummyConn()
        db._write = DummyConn()
        db.close()
    finally:
        pass


def test_db_schema_migration_paths(tmp_path, monkeypatch):
    db = LocalSearchDB(str(tmp_path / "t5.db"))
    try:
        db._fts_enabled = True
        real_conn = db._write

        class WrapCursor:
            def __init__(self):
                self.cur = real_conn.cursor()

            def execute(self, sql, params=()):
                if "CREATE VIRTUAL TABLE IF NOT EXISTS files_fts" in sql:
                    raise sqlite3.OperationalError("fail")
                return self.cur.execute(sql, params)

            def executemany(self, sql, params):
                return self.cur.executemany(sql, params)

            def __getattr__(self, name):
                return getattr(self.cur, name)

        class ConnWrapper:
            def __init__(self, conn):
                self._conn = conn

            def cursor(self):
                return WrapCursor()

            def __getattr__(self, name):
                return getattr(self._conn, name)

        db._write = ConnWrapper(real_conn)
        db._init_schema()
    finally:
        db.close()


def test_db_repo_stats_exception(tmp_path, monkeypatch):
    db = LocalSearchDB(str(tmp_path / "t6.db"))
    try:
        def bad_execute(*_args, **_kwargs):
            raise sqlite3.OperationalError("bad")

        class ConnWrapper:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, *_args, **_kwargs):
                return bad_execute()

            def __getattr__(self, name):
                return getattr(self._conn, name)

        db._read = ConnWrapper(db._read)
        assert db.get_repo_stats(force_refresh=True) == {}
    finally:
        db.close()
