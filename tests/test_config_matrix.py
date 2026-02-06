import json
import pytest
import os
import zlib
import time
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch
from sari.core.indexer.worker import IndexWorker
from sari.core.indexer.main import Indexer
from sari.mcp.server import LocalSearchMCPServer
from sari.core.db import LocalSearchDB

class TestConfigMatrix:
    
    @pytest.fixture
    def mock_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        return LocalSearchDB(str(db_path))

    @pytest.fixture
    def mock_cfg(self):
        cfg = MagicMock()
        cfg.workspace_roots = ["/tmp"]
        cfg.store_content = True
        return cfg

    # 1. Storage Matrix: STORE_CONTENT + COMPRESS
    def test_matrix_storage_compressed(self, mock_db, mock_cfg):
        from sari.core.settings import Settings
        
        # Scenario: Content Stored and Compressed
        with patch.dict("os.environ", {
            "SARI_STORE_CONTENT": "1",
            "SARI_STORE_CONTENT_COMPRESS": "1",
            "SARI_STORE_CONTENT_COMPRESS_LEVEL": "9"
        }):
            s = Settings()
            worker = IndexWorker(mock_cfg, mock_db, None, lambda p, c: ([], []), settings_obj=s)
            
            root = Path("/tmp/test_root_matrix")
            root.mkdir(parents=True, exist_ok=True)
            f = root / "hello.txt"
            content = "Hello " * 100
            f.write_text(content)
            
            res = worker.process_file_task(root, f, f.stat(), int(time.time()), time.time(), False)
            
            assert res["type"] == "changed"
            assert isinstance(res["content"], bytes)
            assert res["content"].startswith(b"ZLIB\0")
            
            # Use real DB connection to verify retrieval
            # First insert the root to satisfy FK
            root_id = res["rel"].split("/")[0]
            mock_db.upsert_root(root_id, str(root), str(root), label="test")
            
            conn = mock_db._write
            cur = conn.cursor()
            mock_db.upsert_files_tx(cur, [(
                res["rel"], "hello.txt", root_id, "repo", res["mtime"], res["size"], 
                res["content"], res["content_hash"], "", 0, 0, "ok", "", "ok", "", 0, 0, 0, res["content_bytes"], res["metadata_json"]
            )])
            conn.commit()
            
            read_back = mock_db.read_file(res["rel"])
            assert read_back == content

    # 2. Search Policy Matrix: SEARCH_FIRST_MODE (warn vs enforce)
    def test_matrix_policy_enforcement(self):
        from sari.mcp.policies import PolicyEngine
        
        # Enforce Mode
        engine = PolicyEngine(mode="enforce")
        # Should block read without search
        res = engine.check_pre_call("read_file")
        assert res is not None
        # Check text in the response (URL encoded in PACK1)
        text = str(res)
        assert "search-first" in text.lower()
        
        # Mark search done
        engine.mark_action("search")
        res = engine.check_pre_call("read_file")
        assert res is None # Allowed now

    # 3. Filter Matrix: MAX_PARSE_BYTES
    def test_matrix_size_filtering(self, mock_db, mock_cfg):
        from sari.core.settings import Settings
        
        with patch.dict("os.environ", {
            "SARI_MAX_PARSE_BYTES": "5"
        }):
            s = Settings()
            worker = IndexWorker(mock_cfg, mock_db, None, lambda p, c: ([], []), settings_obj=s)
            
            root = Path("/tmp/test_root_size_matrix")
            root.mkdir(parents=True, exist_ok=True)
            f = root / "large.txt"
            f.write_text("1234567890")
            
            res = worker.process_file_task(root, f, f.stat(), 0, 0, False)
            assert res["parse_reason"] == "too_large"
            assert res["content"] == ""
