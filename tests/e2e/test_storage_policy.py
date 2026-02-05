import os
import time
import sqlite3
import pytest
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock
from sari.core.db import LocalSearchDB
from sari.core.config import Config
from sari.mcp.cli import cmd_prune

# Mock args for CLI
class MockArgs:
    def __init__(self, workspace, days=None, table=None):
        self.workspace = workspace
        self.days = days
        self.table = table

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "sari.db"
    db = LocalSearchDB(str(db_path))
    # Mock settings
    settings = MagicMock()
    settings.STORAGE_TTL_DAYS_SNIPPETS = 30
    settings.STORAGE_TTL_DAYS_FAILED_TASKS = 7
    settings.STORAGE_TTL_DAYS_CONTEXTS = 30
    db.set_settings(settings)
    
    yield db, db_path
    db.close_all()

def test_prune_logic(temp_db):
    db, db_path = temp_db
    now = int(time.time())
    old_ts_31d = now - (31 * 86400)
    old_ts_8d = now - (8 * 86400)
    recent_ts = now - 3600
    
    # Insert root to satisfy FK
    with db._lock:
        cur = db._write.cursor()
        cur.execute("INSERT OR IGNORE INTO roots (root_id, root_path, real_path, created_ts, updated_ts) VALUES (?,?,?,?,?)", ("root1", "/tmp", "/tmp", now, now))
        db._write.commit()
    
    # 1. Insert data for snippets (TTL 30)
    # snippet: updated_ts is what matters
    with db._lock:
        cur = db._write.cursor()
        # Old snippet (should be deleted)
        cur.execute("INSERT INTO snippets (tag, path, root_id, start_line, end_line, content, content_hash, created_ts, updated_ts) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("old_tag", "p1", "root1", 1, 1, "c", "h", old_ts_31d, old_ts_31d))
        # Recent snippet (keep)
        cur.execute("INSERT INTO snippets (tag, path, root_id, start_line, end_line, content, content_hash, created_ts, updated_ts) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("new_tag", "p2", "root1", 1, 1, "c", "h", recent_ts, recent_ts))
        db._write.commit()
    
    # 2. Insert data for failed_tasks (TTL 7)
    # failed_tasks: ts is what matters
    with db._lock:
        cur = db._write.cursor()
        # Old error (delete)
        cur.execute("INSERT INTO failed_tasks (path, root_id, error, ts, next_retry) VALUES (?,?,?,?,?)",
                   ("old_err", "root1", "e", old_ts_8d, 0))
        # Recent error (keep)
        cur.execute("INSERT INTO failed_tasks (path, root_id, error, ts, next_retry) VALUES (?,?,?,?,?)",
                   ("new_err", "root1", "e", recent_ts, 0))
        db._write.commit()

    # Verify counts before prune
    assert len(db._get_conn().execute("SELECT * FROM snippets").fetchall()) == 2
    assert len(db._get_conn().execute("SELECT * FROM failed_tasks").fetchall()) == 2
    
    # 3. Run Prune (snippets default 30d, failed_tasks default 7d)
    count_s = db.prune_data("snippets", 30)
    count_f = db.prune_data("failed_tasks", 7)
    
    assert count_s == 1
    assert count_f == 1
    
    # Verify counts after prune
    snippets = db._get_conn().execute("SELECT tag FROM snippets").fetchall()
    assert len(snippets) == 1
    assert snippets[0][0] == "new_tag"
    
    failed = db._get_conn().execute("SELECT path FROM failed_tasks").fetchall()
    assert len(failed) == 1
    assert failed[0][0] == "new_err"

def test_cli_prune(tmp_path):
    # Setup Config and DB for CLI mock
    ws_root = tmp_path
    
    # Mock DB object
    mock_db = MagicMock()
    mock_db.settings.STORAGE_TTL_DAYS_SNIPPETS = 30
    mock_db.settings.STORAGE_TTL_DAYS_FAILED_TASKS = 7
    mock_db.settings.STORAGE_TTL_DAYS_CONTEXTS = 30
    
    # Simulate prune_data returning counts
    mock_db.prune_data.side_effect = lambda table, days: 10 if table == "snippets" else 0
    
    # Mock _load_local_db to return our mock_db
    with unittest.mock.patch("sari.mcp.cli._load_local_db", return_value=(mock_db, [], str(ws_root))):
        # Execute CLI command
        args = MockArgs(workspace=str(ws_root), days=None, table=None)
        
        try:
            cmd_prune(args)
        except Exception as e:
            pytest.fail(f"CLI command failed: {e}")
            
        # Verify calls
        # We expect prune_data to be called for all 3 tables with default TTLs
        assert mock_db.prune_data.call_count == 3
        mock_db.prune_data.assert_any_call("snippets", 30)
        mock_db.prune_data.assert_any_call("failed_tasks", 7)
        mock_db.prune_data.assert_any_call("contexts", 30)
    
    # Test with specific arguments
    mock_db.reset_mock()
    with unittest.mock.patch("sari.mcp.cli._load_local_db", return_value=(mock_db, [], str(ws_root))):
        args = MockArgs(workspace=str(ws_root), days=5, table="failed_tasks")
        cmd_prune(args)
        
        # Expect only one call for failed_tasks with 5 days
        assert mock_db.prune_data.call_count == 1
        mock_db.prune_data.assert_called_with("failed_tasks", 5)
