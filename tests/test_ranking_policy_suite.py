#!/usr/bin/env python3
"""
Deckard Ranking & Policy Test Suite.
Consolidates Verification Cycles:
1. Core Edge Cases (Regex, Case, Filters)
2. Policy & Telemetry (Limits, Paging)
3. Hybrid Scoring (Definition, Priors, Proximity)
4. Recency & Noise (Time, Penalty)
5. E2E Scenarios (Real-world use cases)
6. Snippets
7. International
8. Performance
9. Resilience
10. Final
11-15. Symbols & Intelligence
"""
import os
import sys
import shutil
import tempfile
import unittest
import json
import time
import re
import sqlite3
from unittest.mock import patch
from pathlib import Path
import threading

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import LocalSearchDB, SearchOptions
from mcp.tools.search import execute_search
from mcp.telemetry import TelemetryLogger
from tests.pack1_util import parse_pack1

# Attempt to import for Cycle 11+
try:
    from app.indexer import _extract_symbols
except ImportError:
    _extract_symbols = None

# --- Mocks ---
class MockLogger(TelemetryLogger):
    def __init__(self):
        self.last_log = None
    def log_telemetry(self, msg):
        self.last_log = msg

# --- Test Classes ---

class TestRankingEdges(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_cycle_1.db")
        self.db = LocalSearchDB(self.db_path)
        files = [
            ("src/main.py", "def main(): pass", 100),
            ("src/utility.py", "# Helper", 50),
            ("src/User.java", "class User {}", 80),
            ("node_modules/pkg/index.js", "console.log('ignored')", 200),
            ("readme.md", "# Readme", 100),
        ]
        self.db.upsert_files([(f[0], "test_repo", 1000, f[2], f[1], 1000) for f in files])

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_case_sensitivity(self):
        opts = SearchOptions(query="user", limit=10, case_sensitive=False)
        hits, _ = self.db.search_v2(opts)
        self.assertTrue(any(h.path == "src/User.java" for h in hits))
        opts = SearchOptions(query="user", limit=10, case_sensitive=True)
        hits, _ = self.db.search_v2(opts)
        self.assertFalse(any(h.path == "src/User.java" for h in hits))

    def test_regex_mode(self):
        opts = SearchOptions(query="class \w+", limit=10, use_regex=True)
        hits, meta = self.db.search_v2(opts)
        self.assertTrue(meta.get("regex_mode"))
        self.assertTrue(any(h.path == "src/User.java" for h in hits))

class TestRankingPolicy(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_cycle_2.db")
        self.db = LocalSearchDB(self.db_path)
        self.logger = MockLogger()
        files = [(f"doc_{i}.txt", f"content {i}", 10) for i in range(30)]
        self.db.upsert_files([(f[0], "test_repo", 1000, f[2], f[1], 1000) for f in files])

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_limit_cap(self):
        args = {"query": "content", "limit": 100}
        result = execute_search(args, self.db, self.logger)
        data = parse_pack1(result["content"][0]["text"])
        self.assertEqual(int(data["header"]["returned"]), 20)

    def test_exclude_patterns_filtered_total(self):
        args = {"query": "content", "exclude_patterns": ["doc_1"]}
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            result = execute_search(args, self.db, self.logger)
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(data["is_exact_total"])
            self.assertIsNotNone(data.get("filtered_total"))

    def test_search_telemetry_includes_fallback_and_total_mode(self):
        args = {"query": "content"}
        execute_search(args, self.db, self.logger)
        self.assertIsNotNone(self.logger.last_log)
        self.assertIn("tool=search", self.logger.last_log)
        self.assertIn("fallback_used=", self.logger.last_log)
        self.assertIn("total_mode=", self.logger.last_log)

class TestRankingHybrid(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_cycle_3.db")
        self.db = LocalSearchDB(self.db_path)
        def mk_file(path, content): return (path, "test_repo", 1000, len(content), content, 1000)
        self.db.upsert_files([
            mk_file("src/service.py", "class Service:\n    def run(self): pass"),
            mk_file("test/test_service.py", "service = Service()\nservice.run()",),
            mk_file("src/config.json", '{"timeout": 100}'),
            mk_file("dist/config.json", '{"timeout": 100}'),
        ])

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_definition_boost(self):
        opts = SearchOptions(query="Service", limit=5)
        hits, _ = self.db.search_v2(opts)
        self.assertEqual(hits[0].path, "src/service.py")

class TestRankingSnippet(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_ranking_snippet.db")
        self.db = LocalSearchDB(self.db_path)
        content = "user = User()\n" + ("\n" * 8) + "class User:\n    pass"
        self.db.upsert_files([("best_match.py", "repo", 1000, len(content), content, 1000)])

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_snippet_case_preservation(self):
        opts = SearchOptions(query="user", limit=5)
        hits, _ = self.db.search_v2(opts)
        self.assertIn(">>>User<<<", hits[0].snippet)

class TestCycle11(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_cycle_11.db")
        self.db = LocalSearchDB(self.db_path)
    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_symbol_manual_upsert(self):
        self.db.upsert_files([("src/core.py", "repo", 1000, 10, "class Core:\n pass", 1000)])
        symbols = [("src/core.py", "Core", "class", 1, 2, "class Core:", "", "{}", "")]
        self.db.upsert_symbols(symbols)
        opts = SearchOptions(query="Core", limit=5)
        hits, _ = self.db.search_v2(opts)
        self.assertEqual(hits[0].path, "src/core.py")
        self.assertGreater(hits[0].score, 500.0)

class TestCycle12(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_cycle_12.db")
        self.db = LocalSearchDB(self.db_path)
    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_symbol_update_refreshes(self):
        path = "src/dynamic.py"
        self.db.upsert_files([(path, "repo", 1000, 10, "class Old: pass", 1000)])
        self.db.upsert_symbols([(path, "Old", "class", 1, 2, "class Old:", "", "{}", "")])
        self.db.upsert_files([(path, "repo", 2000, 10, "class New: pass", 2000)])
        self.db.upsert_symbols([(path, "New", "class", 1, 2, "class New:", "", "{}", "")])
        hits, _ = self.db.search_v2(SearchOptions(query="Old"))
        self.assertEqual(len(hits), 0)
        hits, _ = self.db.search_v2(SearchOptions(query="New"))
        self.assertEqual(len(hits), 1)

class TestCycle14(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_cycle_14.db")
        self.db = LocalSearchDB(self.db_path)
    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_symbol_repo_filter(self):
        self.db.upsert_files([
            ("backend/User.py", "backend", 1000, 10, "class User:", 1000),
            ("frontend/User.ts", "frontend", 1000, 10, "class User {}", 1000)
        ])
        self.db.upsert_symbols([
            ("backend/User.py", "User", "class", 1, 2, "class User:", "", "{}", ""),
            ("frontend/User.ts", "User", "class", 1, 2, "class User {}", "", "{}", "")
        ])
        opts = SearchOptions(query="User", repo="backend", limit=5)
        hits, _ = self.db.search_v2(opts)
        paths = [h.path for h in hits]
        self.assertIn("backend/User.py", paths)
        self.assertNotIn("frontend/User.ts", paths)

class TestCycle15(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_cycle_15.db")
        self.db = LocalSearchDB(self.db_path)
    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def test_concurrent_ops(self):
        stop_event = threading.Event()
        errors = []
        def writer():
            try:
                for i in range(20):
                    if stop_event.is_set(): break
                    p = f"thread_{i}.py"
                    self.db.upsert_files([(p, "repo", 1000, 10, "class Thread:", 1000)])
                    self.db.upsert_symbols([(p, "Thread", "class", 1, 2, "class Thread:", "", "{}", "")])
                    time.sleep(0.01)
            except Exception as e: errors.append(e)
        def reader():
            try:
                for i in range(20):
                    if stop_event.is_set(): break
                    self.db.search_v2(SearchOptions(query="Thread"))
                    time.sleep(0.01)
            except Exception as e: errors.append(e)
        t1, t2 = threading.Thread(target=writer), threading.Thread(target=reader)
        t1.start(); t2.start()
        t1.join(timeout=5); stop_event.set(); t2.join(timeout=5)
        if errors: self.fail(f"Concurrent errors: {errors}")

if __name__ == "__main__":
    unittest.main()
