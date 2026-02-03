import unittest
import tempfile
import shutil
import os
from pathlib import Path
from app.db import LocalSearchDB, SearchOptions
from mcp.telemetry import TelemetryLogger
from tests.telemetry_helpers import read_log_with_retry

class TestFinalPolish(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_workspace_isolation(self):
        """Verify two different DBs don't leak data."""
        db1_path = str(Path(self.tmp_dir) / "db1.db")
        db2_path = str(Path(self.tmp_dir) / "db2.db")
        
        db1 = LocalSearchDB(db1_path)
        db2 = LocalSearchDB(db2_path)
        
        db1.upsert_files([("file1.txt", "repo1", 0, 0, "apple", 100)])
        db2.upsert_files([("file2.txt", "repo2", 0, 0, "banana", 200)])
        
        # Search DB1 for 'apple'
        hits1, _ = db1.search_v2(SearchOptions(query="apple"))
        self.assertEqual(len(hits1), 1)
        self.assertEqual(hits1[0].path, "file1.txt")
        # Ensure 'banana' not in DB1
        hits1_fail, _ = db1.search_v2(SearchOptions(query="banana"))
        self.assertEqual(len(hits1_fail), 0)
        
        # Search DB2 for 'banana'
        hits2, _ = db2.search_v2(SearchOptions(query="banana"))
        self.assertEqual(len(hits2), 1)
        self.assertEqual(hits2[0].path, "file2.txt")
        
        db1.close()
        db2.close()

    def test_search_ranking_priority(self):
        """Filename match should have higher score than content match."""
        db_path = str(Path(self.tmp_dir) / "rank.db")
        db = LocalSearchDB(db_path)
        
        db.upsert_files([
            ("other.txt", "repo", 100, 10, "This file contains the word target multiple times target target.", 1000),
            ("target.txt", "repo", 100, 10, "Hello world", 1000),
        ])
        
        # Search for 'target'
        hits, _ = db.search_v2(SearchOptions(query="target"))
        
        # target.txt matches by filename stem -> should be first
        self.assertEqual(hits[0].path, "target.txt")
        self.assertIn("filename match", hits[0].hit_reason.lower())
        
        db.close()

    def test_telemetry_logging(self):
        """Verify TelemetryLogger writes to the correct file."""
        log_dir = Path(self.tmp_dir) / "logs"
        logger = TelemetryLogger(log_dir)
        
        test_msg = "test telemetry message"
        logger.log_telemetry(test_msg)
        logger.stop()
        
        log_file = log_dir / "deckard.log"
        self.assertTrue(log_file.exists())
        content = read_log_with_retry(log_dir)
        self.assertIn(test_msg, content)

if __name__ == "__main__":
    unittest.main()
