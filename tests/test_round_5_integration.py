import unittest
import shutil
import tempfile
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import LocalSearchDB
from app.indexer import Indexer, _extract_symbols
from app.config import Config
from mcp.tools.get_implementations import execute_get_implementations
from mcp.tools.search_api_endpoints import execute_search_api_endpoints
from mcp.tools.search import execute_search
from mcp.telemetry import TelemetryLogger

class TestRound5Integration(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.db = LocalSearchDB(self.db_path)
        self.cfg = Config(
            workspace_root=self.test_dir,
            server_host="127.0.0.1",
            server_port=0,
            scan_interval_seconds=60,
            snippet_max_lines=5,
            max_file_bytes=100000,
            db_path=self.db_path,
            include_ext=[],
            include_files=[],
            exclude_dirs=[],
            exclude_globs=[],
            redact_enabled=False,
            commit_batch_size=10
        )
        self.indexer = Indexer(self.cfg, self.db)
        self.logger = TelemetryLogger(self.test_dir)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir)

    def _index_file(self, rel_path, content):
        symbols, relations = _extract_symbols(rel_path, content)
        # Manually upsert for test speed (bypass thread/queue)
        self.db.upsert_files([(rel_path, "repo", 1000, len(content), content, 1000)])
        self.db.upsert_symbols(symbols)
        self.db.upsert_relations(relations)

    def test_01_get_implementations_basic(self):
        code = "class Dog extends Animal {}"
        self._index_file("Dog.java", code)
        
        res = execute_get_implementations({"name": "Animal"}, self.db)
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["results"][0]["implementer_symbol"], "Dog")
        self.assertEqual(res["results"][0]["rel_type"], "extends")

    def test_02_get_implementations_multiple(self):
        self._index_file("A.java", "class A implements I {}")
        self._index_file("B.java", "class B implements I {}")
        
        res = execute_get_implementations({"name": "I"}, self.db)
        self.assertEqual(res["count"], 2)
        implementers = {r["implementer_symbol"] for r in res["results"]}
        self.assertEqual(implementers, {"A", "B"})

    def test_03_search_api_endpoints(self):
        code = '@GetMapping("/api/users")\npublic void getUsers() {}'
        self._index_file("User.java", code)
        
        res = execute_search_api_endpoints({"path": "/api/users"}, self.db)
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["results"][0]["http_path"], "/api/users")

    def test_04_search_docstring_inclusion(self):
        code = 'def foo():\n    """My Docstring"""\n    pass'
        self._index_file("foo.py", code)
        
        # Verify symbol indexing
        syms = self.db.search_symbols("foo")
        self.assertTrue(len(syms) > 0, "Symbol foo should be indexed")
        self.assertEqual(syms[0].get("docstring"), "My Docstring", "Docstring should be indexed")

        res = execute_search({"query": "foo"}, self.db, self.logger)
        content = json.loads(res["content"][0]["text"])
        
        if not content["results"]:
             self.fail(f"Search returned no results for 'foo'. Metadata: {content.get('meta')}")
             
        hit = content["results"][0]
        self.assertEqual(hit.get("docstring"), "My Docstring")

    def test_05_search_docstring_truncate(self):
        long_doc = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        code = f'def bar():\n    """{long_doc}"""\n    pass'
        self._index_file("bar.py", code)
        
        res = execute_search({"query": "bar"}, self.db, self.logger)
        content = json.loads(res["content"][0]["text"])
        hit = content["results"][0]
        self.assertIn("Line 1", hit["docstring"])
        self.assertIn("...", hit["docstring"])
        self.assertNotIn("Line 5", hit["docstring"])

    def test_06_index_robustness_binary(self):
        # Simulate binary content passed to extractor
        # It should catch exception and return empty or partial
        try:
            # Passing garbage text that might look like binary
            _extract_symbols("bin.py", "\x00\x01\x02")
        except Exception:
            self.fail("Indexer crashed on binary content")

    def test_07_inner_class_relations(self):
        # Java inner class
        code = """
class Outer {
    class Inner extends Base {}
}
"""
        self._index_file("Outer.java", code)
        res = execute_get_implementations({"name": "Base"}, self.db)
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["results"][0]["implementer_symbol"], "Inner")

    def test_08_duplicate_class_names(self):
        # Two files defining same class name (unlikely in Java but possible in others or bad code)
        self._index_file("A.java", "class X extends Y {}")
        self._index_file("B.java", "class X extends Z {}")
        
        # Searching implementations of Y should return A.java's X
        res = execute_get_implementations({"name": "Y"}, self.db)
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["results"][0]["implementer_path"], "A.java")

    def test_09_api_search_partial_match(self):
        code = '@GetMapping("/api/v1/users")\npublic void u() {}'
        self._index_file("U.java", code)
        
        # Search for "/users" should match
        res = execute_search_api_endpoints({"path": "users"}, self.db)
        self.assertEqual(res["count"], 1)

    def test_10_invalid_symbol_name(self):
        res = execute_get_implementations({"name": ""}, self.db)
        self.assertIn("error", res)
        self.assertEqual(res["results"], [])

if __name__ == '__main__':
    unittest.main()
