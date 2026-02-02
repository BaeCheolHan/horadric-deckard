import sys
from pathlib import Path
import json
import unittest
import os

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import LocalSearchDB
from app.config import Config
from app.indexer import Indexer
from mcp.tools.search_api_endpoints import execute_search_api_endpoints
from mcp.tools.index_file import execute_index_file

class TestRound3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.abspath("horadric-deckard/tests/test_v2_9.db")
        if os.path.exists(cls.db_path): os.remove(cls.db_path)
        cls.db = LocalSearchDB(cls.db_path)
        cls.cfg = Config(
            workspace_root=os.getcwd(),
            server_host="127.0.0.1",
            server_port=47777,
            scan_interval_seconds=180,
            snippet_max_lines=5,
            max_file_bytes=800000,
            db_path=cls.db_path,
            include_ext=[".py", ".js", ".ts", ".java"],
            include_files=[],
            exclude_dirs=[],
            exclude_globs=[],
            redact_enabled=True,
            commit_batch_size=100
        )
        cls.indexer = Indexer(cls.cfg, cls.db)

    def test_3_1_api_search_integration(self):
        # Index a sample controller
        path = "horadric-deckard/tests/SampleController.java"
        content = Path(path).read_text()
        from app.indexer import _extract_symbols
        symbols = _extract_symbols(path, content)
        self.db.upsert_symbols(symbols)
        
        # Test search
        res = execute_search_api_endpoints({"path": "/api/users"}, self.db)
        self.assertGreater(len(res["results"]), 0)
        self.assertEqual(res["results"][0]["http_path"], "/api/users")

    def test_3_2_index_file_integration(self):
        # Create a new file
        new_file = Path(os.path.abspath("horadric-deckard/tests/NewController.java"))
        new_file.write_text("@RestController\n@RequestMapping(\"/new\")\npublic class New {}")
        
        # Run index_file tool
        res = execute_index_file({"path": str(new_file)}, self.indexer)
        self.assertTrue(res["success"])
        
        # Verify in DB
        # Note: Indexer._process_watcher_event uses relative path
        rel_path = str(new_file.relative_to(os.path.abspath(os.getcwd())))
        meta = self.db.get_file_meta(rel_path)
        self.assertIsNotNone(meta)

if __name__ == "__main__":
    unittest.main()
