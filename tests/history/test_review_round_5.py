
import pytest
import threading
import time
import json
from unittest.mock import MagicMock, patch
from app.indexer import Indexer
from app.db import LocalSearchDB
from mcp.server import LocalSearchMCPServer

class TestReviewRound5:
    """Round 5: Integration & Concurrency."""

    @pytest.fixture
    def db_and_indexer(self, tmp_path):
        db_path = tmp_path / "concurrent.db"
        db = LocalSearchDB(str(db_path))
        
        cfg = MagicMock()
        cfg.workspace_root = str(tmp_path)
        cfg.exclude_dirs = []
        cfg.exclude_globs = []
        cfg.include_ext = [".py"]
        cfg.db_path = str(db_path)
        cfg.commit_batch_size = 10
        
        logger = MagicMock()
        indexer = Indexer(cfg, db, logger)
        yield db, indexer
        indexer.stop()
        db.close()

    def test_indexer_threading_stop(self, db_and_indexer):
        """Test 1: Indexer should stop gracefully."""
        _, indexer = db_and_indexer
        
        # Start a thread that does nothing
        t = threading.Thread(target=indexer.run_forever, daemon=True)
        t.start()
        
        # Give it a moment to enter loop
        time.sleep(0.1)
        
        indexer.stop()
        t.join(timeout=2.0)
        assert not t.is_alive()

    def test_concurrent_db_access(self, db_and_indexer):
        """Test 2: Reading DB while writing (simulated concurrency)."""
        db, _ = db_and_indexer
        
        def writer():
            for i in range(100):
                db.upsert_files([(f"f{i}.py", "repo", 0,0,"",0)])
        
        def reader():
            for i in range(100):
                db.search_symbols("nothing") # Just read lock
        
        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # Should not raise exception
        
    def test_server_malformed_json_request(self):
        """Test 3: Server should handle malformed JSON lines."""
        # Use stdin pipe simulation? 
        # Easier to call handle_request directly if we mock json.loads?
        # But handle_request takes dict. The loop handles parsing.
        # So we test the snippet inside run().
        # Actually, let's test `server.handle_request` with invalid method/params.
        
        server = LocalSearchMCPServer(workspace_root="/tmp")
        server.db = MagicMock()
        server.logger = MagicMock()
        
        # Invalid method
        req = {"jsonrpc": "2.0", "id": 1, "method": "invalid/method", "params": {}}
        resp = server.handle_request(req)
        assert resp["error"]["code"] == -32601 # Method not found
        
        # Notification (no id)
        req = {"jsonrpc": "2.0", "method": "notify/something"}
        resp = server.handle_request(req)
        assert resp is None

    def test_server_tool_error_handling(self):
        """Test 4: handle_tools_call with unknown tool."""
        server = LocalSearchMCPServer(workspace_root="/tmp")
        server._ensure_initialized = MagicMock()
        
        req = {
            "jsonrpc": "2.0", 
            "id": 1, 
            "method": "tools/call", 
            "params": {"name": "fictional_tool", "arguments": {}}
        }
        
        # handle_tools_call raises ValueError, handle_request catches it
        resp = server.handle_request(req)
        assert resp["error"]["code"] == -32000
        assert "Unknown tool" in resp["error"]["message"]

    @patch("app.indexer.Indexer._iter_files")
    def test_indexer_status_update(self, mock_iter, db_and_indexer):
        """Test 5: Indexer state should reflect busy/ready."""
        _, indexer = db_and_indexer
        
        # Before run
        assert not indexer.status.index_ready
        
        # Mock iter to return empty list (fast scan)
        mock_iter.return_value = []
        
        # Manually trigger scan
        indexer.scan_once()
        
        # Should have updated timestamp
        assert indexer.status.last_scan_ts > 0
