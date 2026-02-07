import os
import json
import io
import time
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from sari.mcp.transport import McpTransport
from sari.core.indexer.scanner import Scanner
from sari.core.db import LocalSearchDB
from sari.core.indexer.main import Indexer
from sari.core.config import Config
from sari.core.workspace import WorkspaceManager

def test_mcp_transport_robustness():
    """Test McpTransport with mixed framing and large messages."""
    input_buf = io.BytesIO()
    output_buf = io.BytesIO()
    
    # 1. Write Content-Length message
    msg1 = {"jsonrpc": "2.0", "id": 1, "method": "test"}
    body1 = json.dumps(msg1).encode("utf-8")
    header = f"Content-Length: {len(body1)}\r\n\r\n".encode("ascii")
    input_buf.write(header)
    input_buf.write(body1)
    
    # 2. Write JSONL message
    msg2 = {"jsonrpc": "2.0", "id": 2, "method": "jsonl"}
    input_buf.write((json.dumps(msg2) + "\n").encode("utf-8"))
    
    input_buf.seek(0)
    
    # Test Framed Mode
    transport = McpTransport(input_buf, output_buf, allow_jsonl=False)
    res1 = transport.read_message()
    assert res1 is not None
    assert res1[0]["id"] == 1
    
    # Test JSONL detection
    transport.allow_jsonl = True
    res2 = transport.read_message()
    assert res2 is not None
    assert res2[0]["id"] == 2
    assert res2[1] == "jsonl"
    
    # Test Writing
    transport.write_message({"result": "ok"}, mode="content-length")
    assert b"Content-Length:" in output_buf.getvalue()

def test_scanner_regex_efficiency():
    """Test that Scanner's Regex correctly excludes files and dirs."""
    cfg = MagicMock()
    cfg.exclude_dirs = ["custom_dir"]
    cfg.exclude_globs = ["*.secret"]
    cfg.include_ext = [".py"]
    cfg.settings.MAX_DEPTH = 5
    cfg.settings.FOLLOW_SYMLINKS = False
    
    scanner = Scanner(cfg)
    
    # Check directory exclusion
    assert scanner.exclude_dir_regex.match("custom_dir")
    assert scanner.exclude_dir_regex.match(".git")
    
    # Check file exclusion
    assert scanner.exclude_glob_regex.match("data.secret")
    assert scanner.exclude_glob_regex.match("main.pyc")
    
    # Negative checks
    assert not scanner.exclude_glob_regex.match("main.py")

def test_staging_merge_integrity():
    """Test the atomic merge of staging data into main table."""
    db_path = "/tmp/test_staging.db"
    if os.path.exists(db_path): os.remove(db_path)
    db = LocalSearchDB(db_path)
    
    root_id = "root-test"
    db.upsert_root(root_id, "/tmp", "/tmp", label="test")
    
    cur = db._write.cursor()
    db.create_staging_table(cur)
    
    # Insert 5 files into staging
    rows = []
    for i in range(5):
        rows.append((
            f"{root_id}/file_{i}.py", f"file_{i}.py", root_id, "repo", 100, 10,
            b"content", "hash", "fts", 1000, 0, "ok", "", "ok", "", 0, 0, 0, 10, "{}"
        ))
    db.upsert_files_staging(cur, rows)
    
    # Merge
    db.merge_staging_to_main(cur)
    db._write.commit()
    
    # Verify
    cur.execute("SELECT COUNT(*) FROM files")
    count = cur.fetchone()[0]
    assert count == 5
    db.close_all()
    if os.path.exists(db_path): os.remove(db_path)

def test_fast_track_priority():
    """Test that Fast Track events skip the L1 buffer."""
    test_root = Path("/tmp/sari_fast_track").resolve()
    if test_root.exists(): shutil.rmtree(test_root)
    test_root.mkdir()
    
    db = LocalSearchDB(str(test_root / "sari.db"))
    root_id = WorkspaceManager.root_id(str(test_root))
    db.upsert_root(root_id, str(test_root), str(test_root))
    
    defaults = Config.get_defaults(str(test_root))
    cfg = Config(**defaults)
    indexer = Indexer(cfg, db)
    
    # Create an event
    p = test_root / "hotfix.py"
    p.write_text("print('hotfix')")
    st = p.stat()
    
    # Enqueue with fast_track=True
    task = {
        "kind": "scan_file", "root": test_root, "path": p, "st": st, 
        "scan_ts": int(time.time()), "excluded": False, "fast_track": True
    }
    
    indexer._handle_task(root_id, task)
    
    # Wait for DBWriter to process the task
    indexer.storage.writer.flush(timeout=5.0)
    
    # Should be in DB immediately, not in buffer
    cur = db._read.cursor()
    cur.execute("SELECT COUNT(*) FROM files WHERE path LIKE '%hotfix.py'")
    assert cur.fetchone()[0] == 1
    # Check buffer is empty for this root
    assert len(indexer._l1_buffer.get(root_id, {})) == 0
    
    db.close_all()
    shutil.rmtree(test_root)
