import queue

import pytest

from app.dedup_queue import DedupQueue


def test_dedup_queue_basic():
    dq = DedupQueue()
    assert dq.put("a") is True
    assert dq.put("a") is False

    item = dq.get(block=False)
    assert item == "a"

    dq.task_done(item)

    with pytest.raises(queue.Empty):
        dq.get(block=False)


def test_dedup_queue_batch():
    dq = DedupQueue()
    for i in range(3):
        dq.put(str(i))
    batch = dq.get_batch(max_size=5, timeout=0.01)
    assert len(batch) == 3
    assert dq.qsize() == 0

    empty = dq.get_batch(max_size=2, timeout=0.01)
    assert empty == []
