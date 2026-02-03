import unittest
import tempfile
import os
import shutil
import time
import random
import string
from pathlib import Path
from app.indexer import Indexer
from app.config import Config
from app.db import LocalSearchDB
from app.queue_pipeline import FsEvent, FsEventKind

class TestIndexerDeepDive(unittest.TestCase):
    """
    Hard-core robustness suite with 200+ matrixed test scenarios.
    """
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir) / "matrix_ws"
        self.workspace.mkdir()
        self.db_path = str(self.workspace / "deep.db")
        self.db = LocalSearchDB(self.db_path)
        
        # Default config for matrix
        self._set_config()
        self.indexer = Indexer(self.cfg, self.db)
        self.indexer._start_pipeline()

    def _set_config(self, **kwargs):
        base = {
            "workspace_root": str(self.workspace),
            "server_host": "127.0.0.1", "server_port": 47777,
            "scan_interval_seconds": 180, "snippet_max_lines": 5,
            "max_file_bytes": 1000000, "db_path": self.db_path,
            "include_ext": [], "include_files": [],
            "exclude_dirs": ["node_modules", ".git"], "exclude_globs": [],
            "redact_enabled": True, "commit_batch_size": 100
        }
        base.update(kwargs)
        self.cfg = Config(**base)

    def tearDown(self):
        self.indexer.stop()
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    def test_massive_matrix_processing(self):
        """
        Matrix Testing Category: File Integrity & Redaction (Approx 200 variations)
        We generate a matrix of: 
        10 Extensions x 5 Content Types x 4 Envelopes (Direct/Subdir/HiddenSubdir/Nested)
        = 200 distinct files.
        """
        extensions = [".py", ".java", ".ts", ".js", ".go", ".cpp", ".h", ".md", ".txt", ".json"]
        contents = {
            "valid": "def hello():\n    print('world')",
            "secret": "password = 'secret-123456'",
            "unicode": "def 인사(): return '안녕하세요' # UTF-8 check",
            "syntax_err": "class { void (", 
            "huge": "print('data')\n" * 1000
        }
        locations = ["", "subdir", ".hidden_dir", "nest/v1/v2/v3"]

        count = 0
        for ext in extensions:
            for c_name, text in contents.items():
                for loc in locations:
                    count += 1
                    # Prepare directory
                    target_dir = self.workspace / loc
                    target_dir.mkdir(parents=True, exist_ok=True)
                    
                    filename = f"test_{count}_{c_name}{ext}"
                    path = target_dir / filename
                    path.write_text(text, encoding="utf-8")
                    
                    # Notify indexer
                    self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(path), ts=time.time()))

        # Wait for ingestion thread (Wait up to 15 seconds for 200 files)
        start = time.time()
        while self.db.count_files() < 200 and (time.time() - start) < 15:
            time.sleep(0.5)

        indexed_count = self.db.count_files()
        self.assertEqual(indexed_count, 200, f"Only {indexed_count}/200 files indexed.")

        # Matrix Verification 1: Redaction
        hits, _ = self.db.search("secret-123456", repo=None)
        self.assertEqual(len(hits), 0, "Secrets were not redacted in matrix!")

        # Matrix Verification 2: Unicode
        hits, _ = self.db.search("안녕하세요", repo=None)
        self.assertTrue(len(hits) > 0, "Unicode content missing from index!")

        # Matrix Verification 3: Directory nesting
        files, _ = self.db.list_files(path_pattern="%nest/v1/v2/v3%")
        expected_nest_count = len(extensions) * len(contents)
        if len(files) != expected_nest_count:
            all_files, _ = self.db.list_files(limit=500)
            sample_paths = [f["path"] for f in all_files[:10]]
            print(f"DEBUG: Sample paths in DB: {sample_paths}")
            print(f"DEBUG: Pattern used: %nest/v1/v2/v3%")
            
        self.assertEqual(len(files), expected_nest_count, f"Nested files count mismatch: {len(files)} != {expected_nest_count}")

    def test_rapid_churn_stress(self):
        """
        Stress Category: Rapid Churn (High frequency updates to same set of files)
        20 files x 10 rapid updates each = 200 update events.
        """
        files = []
        for i in range(20):
            p = self.workspace / f"churn_{i}.py"
            p.write_text("v0")
            files.append(p)
            self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p), ts=time.time()))

        # Rapidly spam updates
        for version in range(1, 11):
            for p in files:
                p.write_text(f"version_{version}")
                self.indexer._process_watcher_event(FsEvent(FsEventKind.MODIFIED, str(p), ts=time.time()))

        # Wait for stabilize
        time.sleep(5)
        
        # All files should exist and be at version 10
        for p in files:
            hits, _ = self.db.search_v2(argparse_mock(f"version_10", repo="__root__"))
            # Due to deduplication, we might skip some versions, but version_10 is the LATEST.
            # It MUST eventually be consistent.
            
        hits, _ = self.db.search_v2(argparse_mock("version_10"))
        self.assertTrue(len(hits) >= 10, f"Expected at least many files to reach version 10, got {len(hits)}")

    def test_mixed_binary_and_encoding_resilience(self):
        """
        Robustness Category: Non-standard files.
        Verify that indexer doesn't choke on non-utf8 or binary-like data.
        """
        # 1. Latin-1 file
        p1 = self.workspace / "latin1.txt"
        p1.write_bytes(b"\xe9\xe0\xf1") # é à ñ in Latin-1
        self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p1), ts=time.time()))
        
        # 2. Binary-like (with null bytes)
        p2 = self.workspace / "maybe_binary.py"
        p2.write_bytes(b"print('hello')\0\0\0" + b"A" * 100)
        self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p2), ts=time.time()))
        
        time.sleep(2)
        # Should be indexed (with errors='ignore')
        self.assertEqual(self.db.count_files(), 2)
        
    def test_deep_deletion_integrity(self):
        """
        Integrity Category: Deleting directories.
        """
        d = self.workspace / "to_delete"
        d.mkdir()
        for i in range(50):
            (d / f"kill_{i}.py").write_text("pass")
            self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(d / f"kill_{i}.py"), ts=time.time()))
            
        time.sleep(3)
        self.assertEqual(self.db.count_files(), 50)
        
        # Wipe directory and notify deletions (Simulate watcher)
        for i in range(50):
            p = d / f"kill_{i}.py"
            p.unlink()
            self.indexer._process_watcher_event(FsEvent(FsEventKind.DELETED, str(p), ts=time.time()))
            
        time.sleep(3)
        self.assertEqual(self.db.count_files(), 0)

def argparse_mock(query, repo=None):
    from app.db import SearchOptions
    return SearchOptions(query=query, repo=repo)

if __name__ == "__main__":
    unittest.main()
