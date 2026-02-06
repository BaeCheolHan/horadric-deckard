import pytest
import time
from unittest.mock import MagicMock
from sari.core.db.storage import GlobalStorageManager
from sari.core.indexer.db_writer import DbTask

@pytest.fixture
def mock_db():
    return MagicMock()

def test_storage_manager_singleton(mock_db):
    sm1 = GlobalStorageManager.get_instance(mock_db)
    sm2 = GlobalStorageManager.get_instance(mock_db)
    assert sm1 is sm2
    sm1.stop()

def test_storage_upsert_and_overlay(mock_db):
    sm = GlobalStorageManager(mock_db)
    # row: 0:path, 1:rel, 2:root_id, 3:repo, 4:mtime, 5:size, 6:content, 7:metadata, 8:fts
    row1 = ("path1", "path1", "root1", "repo1", 100, 10, "content", "meta", "fts content")
    
    sm.upsert_files([row1])
    
    # Check if in overlay
    recent = sm.get_recent_files("fts")
    assert len(recent) == 1
    assert recent[0][0] == "path1"
    
    # Upsert older mtime - should be ignored
    row1_old = ("path1", "path1", "root1", "repo1", 50, 10, "content", "meta", "fts content")
    sm.upsert_files([row1_old])
    with sm._overlay_lock:
        assert sm._overlay_files["path1"][4] == 100
        
    # Upsert newer mtime - should update
    row1_new = ("path1", "path1", "root1", "repo1", 200, 10, "content", "meta", "fts content")
    sm.upsert_files([row1_new])
    with sm._overlay_lock:
        assert sm._overlay_files["path1"][4] == 200

def test_storage_delete(mock_db):
    sm = GlobalStorageManager(mock_db)
    row1 = ("path1", "path1", "root1", "repo1", 100, 10, "content", "meta", "fts content")
    sm.upsert_files([row1])
    
    assert "path1" in sm._overlay_files
    
    sm.delete_file("path1")
    assert "path1" not in sm._overlay_files

def test_storage_commit_callback(mock_db):
    sm = GlobalStorageManager(mock_db)
    row1 = ("path1", "path1", "root1", "repo1", 100, 10, "content", "meta", "fts content")
    sm.upsert_files([row1])
    
    assert "path1" in sm._overlay_files
    
    # Simulate DBWriter commit callback
    sm._on_db_commit(["path1"])
    assert "path1" not in sm._overlay_files

def test_storage_queue_load(mock_db):
    sm = GlobalStorageManager(mock_db)
    assert sm.get_queue_load() == 0.0
    
    # Mock writer qsize
    sm.writer.qsize = MagicMock(return_value=2500)
    assert sm.get_queue_load() == 0.5


def test_storage_get_instance_keeps_previous_when_shutdown_incomplete():
    db1 = MagicMock()
    db1.db_path = "/tmp/a.db"
    db2 = MagicMock()
    db2.db_path = "/tmp/b.db"

    GlobalStorageManager._instance = None
    sm1 = GlobalStorageManager.get_instance(db1)
    sm1.shutdown = MagicMock(return_value=False)

    sm2 = GlobalStorageManager.get_instance(db2)
    assert sm2 is sm1

    sm1.stop()
    # cleanup singleton side-effect for other tests
    GlobalStorageManager._instance = None
