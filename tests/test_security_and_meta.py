import unittest
import tempfile
import shutil
import os
from pathlib import Path
import time
from app.indexer import _redact
from app.db import LocalSearchDB

class TestRedaction(unittest.TestCase):
    def test_redact_assignments(self):
        cases = [
            ("password=secret123", "password=***"),
            ("api_key: 'abc-123'", "api_key: '***'"), # Quotes preserved
            ("token = \"xyz-789\"", "token = \"***\""),
        ]
        for inp, exp in cases:
            self.assertEqual(_redact(inp), exp)

class TestMetaExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmp_dir) / "test.db")
        self.db = LocalSearchDB(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    def test_process_package_json(self):
        from app.indexer import Indexer
        from app.config import Config
        from pathlib import Path
        import json

        pkg_path = Path(self.tmp_dir) / "package.json"
        pkg_path.write_text(json.dumps({
            "description": "Test Repo",
            "keywords": ["tag1", "tag2"]
        }))
        
        cfg = Config(
            workspace_root=self.tmp_dir, server_host="127.0.0.1", server_port=47777,
            scan_interval_seconds=180, snippet_max_lines=5,
            max_file_bytes=1000000, db_path=self.db_path,
            include_ext=[".json"], include_files=[],
            exclude_dirs=[], exclude_globs=[],
            redact_enabled=True, commit_batch_size=500
        )
        indexer = Indexer(cfg, self.db)
        indexer._start_pipeline()
        indexer._process_meta_file(pkg_path, "test-repo")
        end = time.time() + 2.0
        meta = None
        while time.time() < end:
            meta = self.db.get_repo_meta("test-repo")
            if meta:
                break
            time.sleep(0.05)
        indexer.stop()
        self.assertIsNotNone(meta)
        self.assertEqual(meta["description"], "Test Repo")
        self.assertIn("tag1", meta["tags"])

if __name__ == "__main__":
    unittest.main()
