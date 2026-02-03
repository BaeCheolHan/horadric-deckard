import time

from app.queue_pipeline import FsEvent, FsEventKind, TaskAction, coalesce_action, split_moved_event


def test_coalesce_delete_wins():
    assert coalesce_action(TaskAction.INDEX, TaskAction.DELETE) == TaskAction.DELETE
    assert coalesce_action(TaskAction.DELETE, TaskAction.INDEX) == TaskAction.DELETE


def test_moved_split():
    evt = FsEvent(kind=FsEventKind.MOVED, path="src/a.txt", dest_path="dst/a.txt", ts=time.time())
    actions = split_moved_event(evt)
    assert actions == [(TaskAction.DELETE, "src/a.txt"), (TaskAction.INDEX, "dst/a.txt")]
