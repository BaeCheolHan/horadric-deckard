import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.indexer import (
    _safe_compile,
    PythonParser,
    _SymbolExtraction,
    Indexer,
    BaseParser,
    GenericRegexParser,
    DBWriter,
)
from app.db import LocalSearchDB
from app.queue_pipeline import FsEvent, FsEventKind, TaskAction, CoalesceTask, DbTask


class DummyLogger:
    def __init__(self):
        self.errors = []
        self.infos = []
        self.telemetry = []
        self._depth = 0

    def log_error(self, msg):
        self.errors.append(msg)

    def log_info(self, msg):
        self.infos.append(msg)

    def log_telemetry(self, msg):
        self.telemetry.append(msg)

    def get_queue_depth(self):
        return self._depth

    def get_drop_count(self):
        return 0


class DummyQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)

    def qsize(self):
        return len(self.items)

    def get_batch(self, max_size=50, timeout=0.1):
        if not self.items:
            return []
        batch = self.items[:max_size]
        self.items = self.items[max_size:]
        return batch


class DummyDBWriter:
    def __init__(self):
        self.items = []
        self.last_commit_ts = 0

    def enqueue(self, task):
        self.items.append(task)

    def qsize(self):
        return len(self.items)

    def stop(self, timeout=0):
        return None


def _mk_cfg(tmp_path, **overrides):
    base = dict(
        workspace_root=str(tmp_path),
        server_host="127.0.0.1",
        server_port=1,
        scan_interval_seconds=1,
        snippet_max_lines=2,
        max_file_bytes=1024,
        db_path=str(tmp_path / "t.db"),
        include_ext=[".py"],
        include_files=[],
        exclude_dirs=[],
        exclude_globs=[],
        redact_enabled=True,
        commit_batch_size=10,
        exclude_content_bytes=100,
        max_workers="bad",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_safe_compile_fallback():
    pat = _safe_compile("[", fallback="(")
    assert pat.pattern == "a^"


def test_base_parser_extract():
    parser = BaseParser()
    with pytest.raises(NotImplementedError):
        parser.extract("a.py", "x")


def test_python_parser_comment_doc():
    src = 'DOC = """\n/*\n * Doc line\n */\n"""\nclass A:\n    pass\n'
    parser = PythonParser()
    symbols, _ = parser.extract("a.py", src)
    assert symbols
    assert "Doc line" in symbols[0][-1]


def test_symbol_extraction_eq():
    a = _SymbolExtraction([("p",)], [])
    b = _SymbolExtraction([("p",)], [])
    assert a == b
    assert a == [("p",)]


def test_generic_regex_parser_call_keywords():
    config = {
        "re_class": _safe_compile(r"\b(class)\s+([a-zA-Z0-9_]+)"),
        "re_method": _safe_compile(r"\b([a-zA-Z0-9_]+)\b\s*\("),
    }
    parser = GenericRegexParser(config, ".java")
    content = "class A { void m() { if (x) { foo(); } } }"
    symbols, relations = parser.extract("A.java", content)
    assert symbols
    assert all(r[3] != "if" for r in relations)


def test_indexer_basic_paths(tmp_path):
    db = LocalSearchDB(str(tmp_path / "db.sqlite"))
    logger = DummyLogger()
    cfg = _mk_cfg(tmp_path, max_workers=-1)
    idx = Indexer(cfg, db, logger=logger)

    idx._event_queue = DummyQueue()
    idx._db_writer = DummyDBWriter()

    assert idx.get_queue_depths()["watcher"] == 0
    assert idx.get_last_commit_ts() == 0

    assert idx._normalize_path("/tmp/not-here") is None

    idx._coalesce_max_keys = 0
    idx._enqueue_action(TaskAction.INDEX, str(tmp_path / "a.py"), time.time())
    assert idx._drop_count_degraded == 1

    idx._coalesce_max_keys = 100
    evt = FsEvent(kind=FsEventKind.MOVED, path=str(tmp_path / "a.py"), dest_path=str(tmp_path / "b.py"), ts=time.time())
    idx._enqueue_fsevent(evt)
    assert idx._event_queue.qsize() >= 2

    idx._enqueue_update_last_seen([])

    db.close()


def test_indexer_handle_index_and_retry(tmp_path):
    db = LocalSearchDB(str(tmp_path / "db2.sqlite"))
    cfg = _mk_cfg(tmp_path)
    idx = Indexer(cfg, db)
    idx._event_queue = DummyQueue()
    idx._db_writer = DummyDBWriter()

    missing_task = CoalesceTask(action=TaskAction.INDEX, path="missing.txt", attempts=0, enqueue_ts=time.time(), last_seen=time.time())
    idx._handle_index_task(missing_task)
    assert idx._db_writer.items

    bad_task = CoalesceTask(action=TaskAction.INDEX, path="bad.txt", attempts=2, enqueue_ts=time.time(), last_seen=time.time())
    idx._retry_task(bad_task, IOError("boom"))
    assert idx._drop_count_degraded == 1

    db.close()


def test_process_file_task_paths(tmp_path):
    db = LocalSearchDB(str(tmp_path / "db3.sqlite"))
    cfg = _mk_cfg(tmp_path, max_file_bytes=1)
    idx = Indexer(cfg, db)

    p = tmp_path / "a.py"
    p.write_text("print('hi')", encoding="utf-8")
    st = p.stat()

    res = idx._process_file_task(tmp_path, p, st, int(time.time()), time.time())
    assert res is None

    cfg = _mk_cfg(tmp_path, max_file_bytes=10000, exclude_content_bytes=5)
    idx = Indexer(cfg, db)
    st = p.stat()
    res = idx._process_file_task(tmp_path, p, st, int(time.time()), time.time())
    assert res and "CONTENT TRUNCATED" in res["content"]

    old_ts = int(time.time()) - 10
    os.utime(p, (old_ts, old_ts))
    st = p.stat()
    db.upsert_files([("a.py", "__root__", int(st.st_mtime), int(st.st_size), "x", int(time.time()))])
    res = idx._process_file_task(tmp_path, p, st, int(time.time()), time.time())
    assert res and res["type"] == "unchanged"

    db.close()


def test_indexer_stop_and_metrics(tmp_path, monkeypatch):
    db = LocalSearchDB(str(tmp_path / "db_stop.sqlite"))
    cfg = _mk_cfg(tmp_path)
    idx = Indexer(cfg, db)

    class BadWatcher:
        def stop(self):
            raise RuntimeError("stop")

    idx.watcher = BadWatcher()

    class BadExec:
        def shutdown(self, wait=False):
            raise RuntimeError("shutdown")

    idx._executor = BadExec()

    class BadLogger(DummyLogger):
        def stop(self, timeout=0):
            raise RuntimeError("log")

    idx.logger = BadLogger()
    idx.stop()

    idx._stop.clear()
    idx.logger = DummyLogger()

    def bad_log(_msg):
        raise RuntimeError("boom")

    idx.logger.log_telemetry = bad_log

    def fake_sleep(_):
        idx._stop.set()

    monkeypatch.setattr(time, "sleep", fake_sleep)
    idx._metrics_loop()
    db.close()


def test_indexer_run_forever_watcher_error(tmp_path, monkeypatch):
    db = LocalSearchDB(str(tmp_path / "db_run.sqlite"))
    cfg = _mk_cfg(tmp_path)
    idx = Indexer(cfg, db, logger=DummyLogger())

    class BadWatcher:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("start")

    monkeypatch.setattr("app.indexer.FileWatcher", BadWatcher)
    idx._stop.set()
    idx.run_forever()
    db.close()


def test_indexer_drain_and_worker(tmp_path):
    db = LocalSearchDB(str(tmp_path / "db_drain.sqlite"))
    cfg = _mk_cfg(tmp_path)
    idx = Indexer(cfg, db, logger=DummyLogger())

    class Q:
        def __init__(self, n):
            self.n = n

        def qsize(self):
            return self.n

    idx._event_queue = Q(1)
    idx._db_writer = Q(2)
    idx._drain_timeout = 0.0
    idx._drain_queues()

    idx._event_queue = None
    idx._worker_loop()
    idx._enqueue_action(TaskAction.INDEX, str(tmp_path / "a.py"), time.time())
    db.close()


def test_dbwriter_exception_paths(tmp_path):
    db = LocalSearchDB(str(tmp_path / "db_writer.sqlite"))
    logger = DummyLogger()
    writer = DBWriter(db, logger=logger, max_wait=0.01)

    class ConnWrapper:
        def __init__(self):
            import sqlite3
            self.conn = sqlite3.connect(":memory:")

        def cursor(self):
            return self.conn.cursor()

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            raise RuntimeError("close")

    db.open_writer_connection = lambda: ConnWrapper()
    writer._stop.set()
    writer.enqueue(DbTask(kind="delete_path", path="a"))

    def boom(_cur, _tasks):
        raise RuntimeError("boom")

    writer._process_batch = boom
    writer._run()
    assert logger.errors
    db.close()


def test_dbwriter_update_last_seen(tmp_path):
    db = LocalSearchDB(str(tmp_path / "db_writer2.sqlite"))
    writer = DBWriter(db)
    cur = db._write.cursor()
    db.upsert_files([("a.py", "__root__", 1, 1, "x", 1)])
    tasks = [DbTask(kind="update_last_seen", paths=["a.py"]) ]
    writer._process_batch(cur, tasks)
    db.close()


def test_indexer_meta_and_process_file_errors(tmp_path, monkeypatch):
    db = LocalSearchDB(str(tmp_path / "db_meta.sqlite"))
    cfg = _mk_cfg(tmp_path)
    idx = Indexer(cfg, db)

    idx._process_meta_file(Path(tmp_path / "a.txt"), "repo1")

    pkg = tmp_path / "package.json"
    pkg.write_text("{bad}", encoding="utf-8")
    idx._process_meta_file(pkg, "repo1")

    pkg.write_text('{"keywords":"a, b", "description":"desc"}', encoding="utf-8")
    idx._process_meta_file(pkg, "repo1")

    pkg.write_text("{}", encoding="utf-8")
    idx._process_meta_file(pkg, "repo1")

    other = tmp_path / "other"
    other.mkdir()
    bad_file = other / "x.txt"
    bad_file.write_text("x", encoding="utf-8")
    st = bad_file.stat()
    res = idx._process_file_task(Path(tmp_path / "root2"), bad_file, st, int(time.time()), time.time())
    assert res is None

    def bad_read(*_args, **_kwargs):
        raise IOError("bad")

    monkeypatch.setattr(Path, "read_text", bad_read, raising=False)
    with pytest.raises(Exception):
        idx._process_file_task(Path(tmp_path), tmp_path / "a.py", st, int(time.time()), time.time(), raise_on_error=True)

    db.close()


def test_iter_entries_and_process_chunk(tmp_path, monkeypatch):
    db = LocalSearchDB(str(tmp_path / "db_iter.sqlite"))
    cfg = _mk_cfg(tmp_path, include_ext=[".txt"], exclude_dirs=["skip*"], exclude_globs=["*.skip"])
    idx = Indexer(cfg, db)

    root = Path(tmp_path)
    (root / "skipdir").mkdir()
    (root / "skipdir" / "a.txt").write_text("x", encoding="utf-8")
    (root / "a.skip").write_text("x", encoding="utf-8")
    good = root / "good.txt"
    good.write_text("x", encoding="utf-8")
    broken = root / "broken.txt"
    try:
        broken.symlink_to(root / "missing_target.txt")
    except Exception:
        pass
    list(idx._iter_file_entries_stream(root))

    entries = []
    for i in range(101):
        p = root / f"f{i}.txt"
        p.write_text("x", encoding="utf-8")
        entries.append((p, p.stat()))

    def fake_process(*_args, **_kwargs):
        return {"type": "unchanged", "rel": "x"}

    idx._process_file_task = fake_process
    calls = {"update": 0}

    def upd(paths):
        calls["update"] += 1

    idx._enqueue_update_last_seen = upd

    idx._process_chunk(root, entries, int(time.time()), time.time(), [], [], [], [])
    assert calls["update"] >= 1

    entries2 = []
    for i in range(50):
        p = root / f"g{i}.txt"
        p.write_text("x", encoding="utf-8")
        entries2.append((p, p.stat()))

    def fake_changed(*_args, **_kwargs):
        return {"type": "changed", "rel": "x", "repo": "__root__", "mtime": 1, "size": 1, "content": "x", "scan_ts": 1, "symbols": [], "relations": []}

    idx._process_file_task = fake_changed
    calls = {"db": 0}

    def enq(*_args, **_kwargs):
        calls["db"] += 1

    idx._enqueue_db_tasks = enq
    idx._process_chunk(root, entries2, int(time.time()), time.time(), [], [], [], [])
    assert calls["db"] >= 1

    idx._enqueue_fsevent = lambda _evt: (_ for _ in ()).throw(RuntimeError("boom"))
    idx._process_watcher_event(FsEvent(kind=FsEventKind.CREATED, path=str(root / "x"), dest_path=None, ts=time.time()))
    assert idx.status.errors >= 1

    db.close()
