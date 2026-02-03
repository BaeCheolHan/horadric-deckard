import unittest
import tempfile
import os
import shutil
import time
import threading
from pathlib import Path
from app.indexer import Indexer
from app.config import Config
from app.db import LocalSearchDB
from app.queue_pipeline import FsEvent, FsEventKind

class TestIndexerRobustness(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir) / "ws"
        self.workspace.mkdir()
        self.db_path = str(self.workspace / "test.db")
        self.db = LocalSearchDB(self.db_path)
        
        self.cfg = Config(
            workspace_root=str(self.workspace),
            server_host="127.0.0.1", 
            server_port=47777,
            scan_interval_seconds=180, 
            snippet_max_lines=5,
            max_file_bytes=1000000,
            db_path=self.db_path,
            include_ext=[".py", ".java"], 
            include_files=[],
            exclude_dirs=[],
            exclude_globs=[],
            redact_enabled=True,
            commit_batch_size=50
        )
        self.indexer = Indexer(self.cfg, self.db)
        self.indexer._start_pipeline()

    def tearDown(self):
        self.indexer.stop()
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    def test_burst_events_and_deduplication(self):
        """Case 1: Simulate 500 file changes in a burst."""
        # Start indexer ingestion loop
        # (It's already started in __init__ daemon thread)
        
        # 1. Create 200 files
        for i in range(200):
            p = self.workspace / f"file_{i}.py"
            p.write_text(f"def func_{i}(): pass")
            self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p), ts=time.time()))
            
        # 2. Immediately modify them multiple times (Burst)
        for i in range(200):
            p = self.workspace / f"file_{i}.py"
            p.write_text(f"def func_{i}_v2(): pass")
            self.indexer._process_watcher_event(FsEvent(FsEventKind.MODIFIED, str(p), ts=time.time()))
            
        # Wait for ingestion to finish
        # The batch size is 50, timeout 1.0. 
        # 200 files should take ~4-5 batch cycles.
        max_wait = 10
        start_time = time.time()
        while self.db.count_files() < 200 and (time.time() - start_time) < max_wait:
            time.sleep(0.5)
            
        self.assertEqual(self.db.count_files(), 200)
        
        # Verify symbols are from V2 (deduper should have handled rapid changes)
        # We check one random file
        hits = self.db.search_symbols("func_10_v2")
        self.assertTrue(len(hits) > 0, "Deduplication or burst handling failed: symbol not found")

    def test_malformed_scripts_resilience(self):
        """Case 2: Malformed Python/Java should not crash indexer."""
        # 1. Syntax Error Python
        p1 = self.workspace / "bad.py"
        p1.write_text("if True: \n    print('missing closure")
        
        # 2. Invalid Token Java
        p2 = self.workspace / "bad.java"
        p2.write_text("class 123Bad { void #@! method() {} }")
        
        self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p1), ts=time.time()))
        self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p2), ts=time.time()))
        
        # Wait a bit
        time.sleep(2)
        
        # Files should still be indexed as text, even if symbol parsing failed
        # Depending on implementation, symbols might be empty or partial.
        # Most importantly, the process must not DIE.
        self.assertEqual(self.db.count_files(), 2)
        
    def test_rapid_delete_modify_cycle(self):
        """Case 3: File is modified then deleted quickly."""
        p = self.workspace / "volatile.py"
        p.write_text("def exist(): pass")
        self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p), ts=time.time()))
        
        # Sudden deletion
        p.unlink()
        self.indexer._process_watcher_event(FsEvent(FsEventKind.DELETED, str(p), ts=time.time()))
        
        time.sleep(2)
        
        # Should NOT be in DB
        self.assertEqual(self.db.count_files(), 0)
        
    def test_concurrent_search_during_indexing(self):
        """Case 4: Search while indexer is busy writing."""
        # Fill queue with many tasks
        for i in range(100):
            p = self.workspace / f"stress_{i}.py"
            p.write_text("class Stress { void work() {} }")
            self.indexer._process_watcher_event(FsEvent(FsEventKind.CREATED, str(p), ts=time.time()))
            
        # Perform many concurrent searches
        errors = []
        def search_thread():
            try:
                for _ in range(50):
                    self.db.search("Stress", repo=None)
            except Exception as e:
                errors.append(e)
                
        threads = [threading.Thread(target=search_thread) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        self.assertEqual(len(errors), 0, f"Concurrent search/index caused errors: {errors}")

if __name__ == "__main__":
    unittest.main()
