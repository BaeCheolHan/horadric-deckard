import unittest
import tempfile
import shutil
from pathlib import Path

from app.config import Config
from app.db import LocalSearchDB
from app.indexer import Indexer


class TestIndexerStreamingScan(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir) / "ws"
        self.workspace.mkdir()
        self.db_path = str(self.workspace / "test.db")
        self.db = LocalSearchDB(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    def test_streaming_scan_counts_and_indexes(self):
        (self.workspace / "one.txt").write_text("hello")
        (self.workspace / "two.txt").write_text("world")
        (self.workspace / "skip.md").write_text("ignore")

        cfg = Config(
            workspace_roots=[str(self.workspace)],
            workspace_root=str(self.workspace),
            server_host="127.0.0.1",
            server_port=47777,
            scan_interval_seconds=180,
            snippet_max_lines=5,
            max_file_bytes=1000,
            db_path=self.db_path,
            include_ext=[".txt"],
            include_files=[],
            exclude_dirs=[],
            exclude_globs=[],
            redact_enabled=False,
            commit_batch_size=500,
        )

        indexer = Indexer(cfg, self.db)
        indexer.scan_once()
        indexer.stop()

        self.assertEqual(indexer.status.scanned_files, 2)
        paths = self.db.get_all_file_paths()
        self.assertTrue(any(p.endswith("one.txt") for p in paths))
        self.assertTrue(any(p.endswith("two.txt") for p in paths))
        self.assertNotIn("skip.md", paths)


if __name__ == "__main__":
    unittest.main()
