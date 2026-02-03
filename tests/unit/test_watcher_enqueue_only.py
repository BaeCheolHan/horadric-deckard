import time

from app.config import Config
from app.indexer import Indexer
from app.queue_pipeline import FsEvent, FsEventKind


class DummyDB:
    def open_writer_connection(self):
        raise AssertionError("DB writer should not start during this test")


def test_watcher_callback_enqueues_only(tmp_path):
    cfg = Config(**Config.get_defaults(str(tmp_path)))
    idx = Indexer(cfg, DummyDB(), logger=None)
    evt = FsEvent(kind=FsEventKind.MODIFIED, path=str(tmp_path / "a.txt"), ts=time.time())
    idx._process_watcher_event(evt)
    assert idx._event_queue.qsize() == 1
