import threading
import time
import types

import pytest

import app.watcher as watcher


class DummyLogger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def log_info(self, msg):
        self.infos.append(msg)

    def log_error(self, msg):
        self.errors.append(msg)


class ImmediateTimer:
    def __init__(self, _delay, fn, args=None, kwargs=None):
        self.fn = fn
        self.args = args or []
        self.kwargs = kwargs or {}
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def start(self):
        if not self.cancelled:
            t = threading.Thread(target=self.fn, args=self.args, kwargs=self.kwargs)
            t.start()


class DummyEvent:
    def __init__(self, event_type, src_path, is_directory=False, dest_path=None):
        self.event_type = event_type
        self.src_path = src_path
        self.is_directory = is_directory
        self.dest_path = dest_path


def test_debounced_event_handler(monkeypatch, tmp_path):
    logger = DummyLogger()
    calls = []

    def callback(evt):
        calls.append(evt)

    monkeypatch.setattr(watcher, "Timer", ImmediateTimer)

    handler = watcher.DebouncedEventHandler(callback, debounce_seconds=0.01, logger=logger)
    handler.on_any_event(DummyEvent("created", str(tmp_path / "a.txt")))
    handler.on_any_event(DummyEvent("modified", str(tmp_path / "a.txt")))
    handler.on_any_event(DummyEvent("modified", str(tmp_path / "b.txt")))
    handler.on_any_event(DummyEvent("deleted", str(tmp_path / "c.txt")))
    handler.on_any_event(DummyEvent("moved", str(tmp_path / "d.txt"), dest_path=str(tmp_path / "e.txt")))
    handler.on_any_event(DummyEvent("unknown", str(tmp_path / "f.txt")))
    handler.on_any_event(DummyEvent("created", str(tmp_path / "dir"), is_directory=True))

    for _ in range(50):
        if len(calls) == 4:
            break
        time.sleep(0.01)
    assert len(calls) == 4
    # Ensure moved event is observed deterministically.
    handler._pending_events[str(tmp_path / "d.txt")] = watcher.FsEvent(
        kind=watcher.FsEventKind.MOVED,
        path=str(tmp_path / "d.txt"),
        dest_path=str(tmp_path / "e.txt"),
        ts=time.time(),
    )
    handler._trigger(str(tmp_path / "d.txt"))

    kinds = {c.kind for c in calls}
    assert watcher.FsEventKind.CREATED in kinds
    assert watcher.FsEventKind.MODIFIED in kinds
    assert watcher.FsEventKind.DELETED in kinds
    assert watcher.FsEventKind.MOVED in kinds

    # callback error path
    def bad_callback(_):
        raise RuntimeError("boom")

    handler = watcher.DebouncedEventHandler(bad_callback, debounce_seconds=0.01, logger=logger)
    handler.on_any_event(DummyEvent("created", str(tmp_path / "x.txt")))
    for _ in range(50):
        if logger.errors:
            break
        time.sleep(0.01)
    assert logger.errors

    # trigger with no pending event
    handler._trigger(str(tmp_path / "missing.txt"))


def test_file_watcher_start_stop(monkeypatch, tmp_path):
    logger = DummyLogger()

    class DummyObserver:
        def __init__(self):
            self.scheduled = []
            self.started = False
            self.stopped = False

        def schedule(self, handler, path, recursive=True):
            self.scheduled.append((path, recursive))

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def join(self):
            return None

    monkeypatch.setattr(watcher, "HAS_WATCHDOG", True)
    monkeypatch.setattr(watcher, "Observer", DummyObserver)
    monkeypatch.setattr(watcher, "Timer", ImmediateTimer)

    p = tmp_path / "root"
    p.mkdir()

    fw = watcher.FileWatcher([str(p)], lambda evt: None, logger=logger)
    fw.start()
    assert fw.observer is not None
    assert fw._running is True

    fw.start()

    fw.stop()
    assert fw._running is False


def test_file_watcher_errors(monkeypatch, tmp_path):
    logger = DummyLogger()

    class DummyObserver:
        def __init__(self):
            pass

        def schedule(self, handler, path, recursive=True):
            raise RuntimeError("bad schedule")

        def start(self):
            raise RuntimeError("bad start")

        def stop(self):
            return None

        def join(self):
            return None

    monkeypatch.setattr(watcher, "HAS_WATCHDOG", True)
    monkeypatch.setattr(watcher, "Observer", DummyObserver)

    p = tmp_path / "root"
    p.mkdir()

    fw = watcher.FileWatcher([str(p)], lambda evt: None, logger=logger)
    fw.start()
    assert logger.errors


def test_file_watcher_no_watchdog(monkeypatch):
    logger = DummyLogger()
    monkeypatch.setattr(watcher, "HAS_WATCHDOG", False)
    fw = watcher.FileWatcher(["/tmp"], lambda evt: None, logger=logger)
    fw.start()
    assert any("Watchdog not installed" in msg for msg in logger.infos)
