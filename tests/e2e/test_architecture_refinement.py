
import os
import sys
import time
import shutil
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock
import logging
logging.basicConfig(level=logging.INFO)

# Prepend current directory to ensure we load local sari
sys.path.insert(0, os.getcwd())

try:
    import sari
    print(f"DEBUG: Loaded sari from {sari.__file__}")
except ImportError:
    pass

from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.core.indexer import Indexer
# Skip settings import due to environment issues

def test_architecture_refinement():
    print("START: test_architecture_refinement")
    # Setup
    workspace_dir = tempfile.mkdtemp()
    workspace = Path(workspace_dir).resolve()
    print(f"DEBUG: Workspace at {workspace}")
    
    try:
        # Create dummy files
        (workspace / "file1.txt").write_text("Hello World content for FTS check")
        (workspace / "file2.txt").write_text("Another file")

        db_path = workspace / "test.db"
        db = LocalSearchDB(str(db_path))
        
        # Test 1: 0-cost FTS (ENABLE_FTS = False)
        # Mock Settings
        # We don't import Settings class, just mock the interface
        mock_settings = MagicMock()
        mock_settings.get_bool.side_effect = lambda k, d=False: False if k == "ENABLE_FTS" else d
        def get_int_mock(k, d=0):
            if k == "FTS_MAX_BYTES": return 1000
            if k == "INDEX_L1_BATCH_SIZE": return 1
            if k == "INDEX_WORKERS": return 1
            if k == "INDEX_MEM_MB": return 0
            if k == "DB_BATCH_SIZE": return 1 # Also for DBWriter
            return d
        mock_settings.get_int.side_effect = get_int_mock
        
        # Attribute access
        mock_settings.ENABLE_FTS = False
        mock_settings.FTS_MAX_BYTES = 1000
        mock_settings.INDEX_L1_BATCH_SIZE = 1
        mock_settings.INDEX_WORKERS = 1
        mock_settings.INDEX_MEM_MB = 0
        mock_settings.MAX_PARSE_BYTES = 1024*1024
        mock_settings.MAX_AST_BYTES = 1024*1024
        mock_settings.STORE_CONTENT_COMPRESS = False
        mock_settings.ENGINE_MAX_DOC_BYTES = 1000
        mock_settings.AST_CACHE_ENTRIES = 10
        
        # Config
        # Config
        # Config (legacy dataclass requires many args if not using defaults)
        # Based on inspection, most fields don't have defaults in init?
        # Let's provide them.
        cfg = Config(
            workspace_roots=[str(workspace)],
            workspace_root=str(workspace),
            # providing dummies for others
            server_host="127.0.0.1", server_port=47779,
            scan_interval_seconds=300, snippet_max_lines=5, max_file_bytes=1000000,
            db_path=str(db_path),
            include_ext=[".txt"], include_files=[],
            exclude_dirs=[], exclude_globs=[],
            redact_enabled=False, commit_batch_size=50,
            store_content=True, gitignore_lines=[],
            # Optional args
            http_api_port=47777,
        )
        
        # Mock logger
        mock_logger = MagicMock()
        
        # Explicitly upsert root (Fix for FK errors)
        try:
            from sari.core.workspace import WorkspaceManager
            root_id = WorkspaceManager.root_id(str(workspace))
            print(f"DEBUG: Upserting root {root_id} -> {workspace}")
            db.upsert_root(root_id, str(workspace), str(workspace.resolve()))
        except Exception as e:
            print(f"FAIL: Root upsert failed: {e}")
            raise

        # Initialize Indexer
        print("DEBUG: Initializing Indexer")
        indexer = Indexer(cfg, db, logger=mock_logger, settings_obj=mock_settings)
        
        # Run Indexing in thread
        idx_thread = threading.Thread(target=indexer.run_forever, daemon=True)
        idx_thread.start()
        
        print("DEBUG: Indexer started. Waiting for scan...")
        time.sleep(3) # Wait for scan
        
        print(f"DEBUG: Indexer Status: scanned={indexer.status.scanned_files}, indexed={indexer.status.indexed_files}, errors={indexer.status.errors}")
        print(f"DEBUG: Active Roots: {indexer._active_roots}")
        
        # Verify FTS content is empty
        cur = db._get_conn().cursor()
        rows = cur.execute("SELECT path, fts_content FROM files").fetchall()
        print(f"DEBUG: Scanned rows: {len(rows)}")
        assert len(rows) >= 2, f"Should have indexed 2 files, got {len(rows)}"
        for r in rows:
            assert r[1] == "", f"FTS content should be empty for {r[0]}"
            
        print("PASS: 0-cost FTS verified")
        
        # Verify Metrics
        metrics = indexer.get_performance_metrics()
        print(f"DEBUG: Metrics: {metrics}")
        assert "latency_p50" in metrics
        
        print("PASS: Metrics verified")
        
        # Test 3: DLQ (Engine Failure)
        print("DEBUG: Testing DLQ")
        mock_engine = MagicMock()
        mock_engine.upsert_documents.side_effect = Exception("Simulated Engine Failure")
        # Ensure engine check passes
        db.set_engine(mock_engine)
        
        # Create fail file
        (workspace / "fail_file.txt").write_text("This should fail engine sync")
        
        # Trigger event manually
        from sari.core.queue_pipeline import FsEvent, FsEventKind
        # Try to use indexer public API if possible to enqueue, or private
        
        # Test 3: DLQ (Engine Failure)
        print("DEBUG: Testing DLQ")
        # Trigger event for new file which fails engine sync
        # We need mock engine to fail ONLY for this file?
        # No, mock engine fails everything.
        
        # ... (rest of test)
        # Trigger event manually
        from sari.core.queue_pipeline import FsEvent, FsEventKind
        # Try to use indexer public API if possible to enqueue, or private
        indexer._enqueue_fsevent(FsEvent(FsEventKind.CREATED, str(workspace / "fail_file.txt"), root=str(workspace)))
        
        time.sleep(2)
        
        failed = cur.execute("SELECT path, error FROM failed_tasks").fetchall()
        assert len(failed) > 0, "Should have failed tasks"
        assert "Simulated Engine Failure" in failed[0][1]
        
        print("PASS: DLQ verified")
        
        # Test 4: Retry
        print("DEBUG: Testing Retry")
        # Fix engine
        mock_engine.upsert_documents.side_effect = None
        
        # Force next_retry to past
        cur.execute("UPDATE failed_tasks SET next_retry = ?", (int(time.time()) - 10,))
        db._write.commit()
        
        # Trigger retry manually
        indexer._retry_failed_tasks()
        
        time.sleep(5) # Wait for retry
        
        failed_after = cur.execute("SELECT path FROM failed_tasks").fetchall()
        print(f"DEBUG: Failed after retry: {failed_after}")
        assert len(failed_after) == 0, "DLQ should be cleared"
        
        print("PASS: Retry verified")
        
        indexer.stop()
        idx_thread.join(timeout=1)
        print("ALL TESTS PASSED")

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        try:
            shutil.rmtree(workspace_dir)
        except:
            pass

if __name__ == "__main__":
    test_architecture_refinement()
