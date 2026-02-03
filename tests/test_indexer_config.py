import unittest
import tempfile
import shutil
import os
from pathlib import Path
from app.db import LocalSearchDB
from app.indexer import Indexer
from app.config import Config
from mcp.telemetry import TelemetryLogger

class TestIndexerConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir) / "ws"
        self.workspace.mkdir()
        self.db_path = str(self.workspace / "test.db")
        self.db = LocalSearchDB(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    def test_exclude_globs(self):
        """Verify files matching exclude_globs are skipped."""
        (self.workspace / "normal.py").write_text("content")
        (self.workspace / "secret.key").write_text("secret")
        (self.workspace / "temp_file.tmp").write_text("temp")
        
        cfg = Config(
            workspace_roots=[str(self.workspace)],
            workspace_root=str(self.workspace),
            server_host="127.0.0.1", server_port=47777,
            scan_interval_seconds=180, snippet_max_lines=5,
            max_file_bytes=1000, db_path=self.db_path,
            include_ext=[".py", ".key", ".tmp"], include_files=[],
            exclude_dirs=[], exclude_globs=["*.key", "temp_*"],
            redact_enabled=False, commit_batch_size=500
        )
        
        indexer = Indexer(cfg, self.db)
        indexer.scan_once()
        indexer.stop()
        
        paths = self.db.get_all_file_paths()
        self.assertTrue(any(p.endswith("normal.py") for p in paths), f"normal.py not found in {paths}")
        self.assertFalse(any(p.endswith("secret.key") for p in paths))
        self.assertFalse(any(p.endswith("temp_file.tmp") for p in paths))

    def test_max_file_size_limit(self):
        """Verify files exceeding max_file_bytes are skipped."""
        large_file = self.workspace / "large.txt"
        large_file.write_text("a" * 2000)
        
        small_file = self.workspace / "small.txt"
        small_file.write_text("a" * 100)
        
        cfg = Config(
            workspace_roots=[str(self.workspace)],
            workspace_root=str(self.workspace),
            server_host="127.0.0.1", server_port=47777,
            scan_interval_seconds=180, snippet_max_lines=5,
            max_file_bytes=500, db_path=self.db_path,
            include_ext=[".txt"], include_files=[],
            exclude_dirs=[], exclude_globs=[],
            redact_enabled=False, commit_batch_size=500
        )
        
        indexer = Indexer(cfg, self.db)
        indexer.scan_once()
        indexer.stop()
        
        paths = self.db.get_all_file_paths()
        self.assertTrue(any(p.endswith("small.txt") for p in paths))
        self.assertFalse(any(p.endswith("large.txt") for p in paths))

    def test_telemetry_readonly_dir(self):
        """Verify logger handles read-only directory gracefully."""
        readonly_dir = Path(self.tmp_dir) / "readonly"
        readonly_dir.mkdir()
        
        logger = TelemetryLogger(readonly_dir)
        # Make directory non-writable
        os.chmod(readonly_dir, 0o444)
        
        try:
            # Should not raise exception
            logger.log_telemetry("this should fail gracefully")
        finally:
            try:
                logger.stop()
            except Exception:
                pass
            os.chmod(readonly_dir, 0o777)

if __name__ == "__main__":
    unittest.main()
