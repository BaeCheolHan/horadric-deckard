import pytest
import sqlite3
import os
import zlib
import time
from sari.core.db.main import LocalSearchDB

@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "test.db"
    db_obj = LocalSearchDB(str(db_file))
    # Ensure root1 exists for foreign key constraints
    db_obj.upsert_root("root1", str(tmp_path), str(tmp_path), "TestRoot")
    yield db_obj
    db_obj.close_all()

def test_db_init(db):
    assert os.path.exists(db.db_path)
    with db._get_conn() as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "roots" in table_names
        assert "files" in table_names

def test_db_roots(db):
    # root1 already upserted in fixture
    roots = db.get_roots()
    assert any(r["root_id"] == "root1" for r in roots)

def test_db_files_upsert_search(db):
    row1 = ("path/to/file.py", "to/file.py", "root1", "repo1", 100, 50, "print('hi')", "hash1", "print hi", 200, 0, "ok", "", "none", "", False, False, False, 12, "{}")
    with db._lock:
        cur = db._write.cursor()
        db.upsert_files_tx(cur, [row1])
        db._write.commit()
    results = db.search_files("file.py")
    assert len(results) == 1
    assert results[0]["path"] == "path/to/file.py"

def test_db_read_file(db):
    content = "Hello World" * 10
    compressed = b"ZLIB\0" + zlib.compress(content.encode("utf-8"))
    row1 = ("path1", "path1", "root1", "repo1", 100, 50, compressed, "hash1", "hello", 200, 0, "ok", "", "none", "", False, False, False, 12, "{}")
    with db._lock:
        cur = db._write.cursor()
        db.upsert_files_tx(cur, [row1])
        db._write.commit()
    read = db.read_file("path1")
    assert read == content

def test_db_read_file_bad_zlib_falls_back_to_disk(db, tmp_path):
    rel = "fallback.txt"
    real_file = tmp_path / rel
    real_file.write_text("disk fallback", encoding="utf-8")
    bad = b"ZLIB\0not-really-zlib"
    row = (f"root1/{rel}", rel, "root1", "repo1", 100, 50, bad, "hash1", "fallback", 200, 0, "ok", "", "none", "", False, False, False, 12, "{}")
    with db._lock:
        cur = db._write.cursor()
        db.upsert_files_tx(cur, [row])
        db._write.commit()
    assert db.read_file(f"root1/{rel}") == "disk fallback"

def test_db_prune_files(db):
    now = int(time.time())
    row_old = ("old_file", "old_file", "root1", "repo1", 100, 50, "old", "hash1", "old", now - 100, 0, "ok", "", "none", "", False, False, False, 3, "{}")
    row_new = ("new_file", "new_file", "root1", "repo1", 100, 50, "new", "hash2", "new", now, 0, "ok", "", "none", "", False, False, False, 3, "{}")
    with db._lock:
        cur = db._write.cursor()
        db.upsert_files_tx(cur, [row_old, row_new])
        db._write.commit()
    pruned_count = db.prune_old_files("root1", now - 50)
    assert pruned_count == 1
    assert db.read_file("old_file") is None
    assert db.read_file("new_file") == "new"

def test_db_failed_tasks(db):
    row = ("fail_path", "root1", 1, "some error", int(time.time()), 0, "{}")
    with db._lock:
        cur = db._write.cursor()
        db.upsert_failed_tasks_tx(cur, [row])
        db._write.commit()
    total, high = db.count_failed_tasks()
    assert total == 1
    failed = db.get_failed_tasks()
    assert len(failed) == 1
    with db._lock:
        cur = db._write.cursor()
        db.clear_failed_tasks_tx(cur, ["fail_path"])
        db._write.commit()
    assert db.count_failed_tasks()[0] == 0


def test_db_migration_precheck_never_deletes_file(tmp_path):
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_ts INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version, applied_ts) VALUES (?, ?)", (0, int(time.time())))
    conn.execute("CREATE TABLE keep_me (v TEXT)")
    conn.execute("INSERT INTO keep_me(v) VALUES ('ok')")
    conn.commit()
    conn.close()

    db = LocalSearchDB(str(db_file))
    row = db._read.execute("SELECT v FROM keep_me").fetchone()
    assert row[0] == "ok"
    db.close_all()
