import unittest
import tempfile
import os
import shutil
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parents[2]))

from app.db import LocalSearchDB
from mcp.tools._util import pack_encode_id, pack_encode_text, pack_header, pack_line
from mcp.tools.list_files import execute_list_files
from mcp.tools.search import execute_search
from mcp.tools.search_symbols import execute_search_symbols
from mcp.tools.status import execute_status
from mcp.tools.repo_candidates import execute_repo_candidates
from tests.pack1_util import parse_pack1

class TestPack1Comprehensive(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmp_dir) / "test.db")
        self.db = LocalSearchDB(self.db_path)
        self.logger = MagicMock()
        # Default to PACK format
        self.env_patcher = patch.dict(os.environ, {"DECKARD_FORMAT": "pack"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    # --- 1. Infrastructure Tests (Util) ---

    def test_01_encoders(self):
        """Test ENC_ID and ENC_TEXT encoding rules."""
        # ENC_ID: safe="/._-:@"
        self.assertEqual(pack_encode_id("path/to/file.py"), "path/to/file.py")
        self.assertEqual(pack_encode_id("file with space.py"), "file%20with%20space.py")
        self.assertEqual(pack_encode_id("user@domain"), "user@domain")
        
        # ENC_TEXT: safe="" (everything encoded except alphanumeric)
        self.assertEqual(pack_encode_text("hello world"), "hello%20world")
        self.assertEqual(pack_encode_text("path/to"), "path%2Fto") # slash is encoded in TEXT

    def test_02_builders(self):
        """Test header and line builders."""
        header = pack_header("tool", {"k": "v"}, returned=10, total=100, total_mode="exact")
        self.assertTrue(header.startswith("PACK1 tool=tool ok=true"))
        
        line_kv = pack_line("r", {"a": "1", "b": "2"})
        self.assertEqual(line_kv, "r:a=1 b=2")
        
        line_single = pack_line("p", single_value="val")
        self.assertEqual(line_single, "p:val")

    # --- 2. List Files Tests ---

    def test_03_list_files_basic(self):
        """Verify list_files returns correct PACK1 structure."""
        self.db.upsert_files([("src/main.py", "repo1", 0, 0, "", 0)])
        res = execute_list_files({"repo": "repo1"}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertEqual(data["tool"], "list_files")
        self.assertEqual(data["header"]["returned"], "1")
        self.assertEqual(data["records"][0]["kind"], "p")
        self.assertEqual(data["records"][0]["value"], "src/main.py")

    def test_04_list_files_limit_clamping(self):
        """Verify list_files clamps limit to 200."""
        # Insert 250 files
        files = [(f"f{i}.txt", "repo1", 0, 0, "", 0) for i in range(250)]
        self.db.upsert_files(files)
        
        res = execute_list_files({"repo": "repo1", "limit": 500}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertEqual(data["header"]["limit"], "200")
        self.assertEqual(len(data["records"]), 200)

    def test_05_list_files_truncation(self):
        """Verify truncation line appears when results > limit."""
        files = [(f"f{i}.txt", "repo1", 0, 0, "", 0) for i in range(15)]
        self.db.upsert_files(files)
        
        res = execute_list_files({"repo": "repo1", "limit": 10}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertEqual(data["header"]["returned"], "10")
        self.assertIn("truncation", data["meta"])
        self.assertEqual(data["meta"]["truncation"]["truncated"], "true")
        self.assertEqual(data["meta"]["truncation"]["next"], "use_offset")
        self.assertEqual(data["meta"]["truncation"]["offset"], "10")

    def test_06_list_files_encoding(self):
        """Verify special characters in paths are encoded."""
        self.db.upsert_files([("path with spaces.py", "repo1", 0, 0, "", 0)])
        res = execute_list_files({"repo": "repo1"}, self.db, self.logger, [])
        # Check raw text to ensure it IS encoded
        raw_text = res["content"][0]["text"]
        self.assertIn("p:path%20with%20spaces.py", raw_text)
        
        # Check parsed
        data = parse_pack1(raw_text)
        self.assertEqual(data["records"][0]["value"], "path with spaces.py")

    # --- 3. Search Symbols Tests ---

    def test_07_search_symbols_formatting(self):
        """Verify search_symbols h: record format."""
        self.db.upsert_files([("src/user.py", "repo1", 0, 0, "", 0)])
        self.db.upsert_symbols([("src/user.py", "User", "class", 10, 20, "class User:", "", "{}", "")])
        
        res = execute_search_symbols({"query": "User"}, self.db, [])
        data = parse_pack1(res["content"][0]["text"])
        
        rec = data["records"][0]
        self.assertEqual(rec["kind"], "h")
        self.assertEqual(rec["data"]["name"], "User")
        self.assertEqual(rec["data"]["kind"], "class")
        self.assertEqual(rec["data"]["line"], "10")

    def test_08_search_symbols_limit(self):
        """Verify search_symbols hard limit is 50."""
        # Insert 60 symbols
        symbols = [("f.py", f"Sym{i}", "func", i, i, "", "", "{}", "") for i in range(60)]
        self.db.upsert_files([("f.py", "r", 0, 0, "", 0)])
        self.db.upsert_symbols(symbols)
        
        res = execute_search_symbols({"query": "Sym", "limit": 100}, self.db, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertEqual(data["header"]["limit"], "50")
        self.assertEqual(len(data["records"]), 50)

    # --- 4. Status Tests ---

    def test_09_status_metrics(self):
        """Verify status returns m: records."""
        res = execute_status({}, None, self.db, None, "/root", "1.0")
        data = parse_pack1(res["content"][0]["text"])
        
        metrics = {r["data"].keys().__iter__().__next__(): r["data"].values().__iter__().__next__() for r in data["records"] if r["kind"] == "m"}
        self.assertIn("fts_enabled", metrics)
        self.assertIn("workspace_root", metrics)

    def test_10_status_details(self):
        """Verify status details=true includes repo stats."""
        self.db.upsert_files([("f1", "repoA", 0, 0, "", 0)])
        res = execute_status({"details": True}, None, self.db, None, "/root", "1.0")
        data = parse_pack1(res["content"][0]["text"])
        
        # Check for repo_repoA metric (keys are encoded if needed, but simple here)
        found = False
        for r in data["records"]:
            if r["kind"] == "m" and "repo_repoA" in r["data"]:
                self.assertEqual(r["data"]["repo_repoA"], "1")
                found = True
        self.assertTrue(found)

    # --- 5. Search (Full Text) Tests ---

    def test_11_search_basic(self):
        """Verify search returns r: records."""
        self.db.upsert_files([("src/main.py", "repo1", 0, 0, "def hello(): pass", 0)])
        res = execute_search({"query": "hello"}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertEqual(data["tool"], "search")
        rec = data["records"][0]
        self.assertEqual(rec["kind"], "r")
        self.assertEqual(rec["data"]["path"], "src/main.py")
        self.assertIn("hello", rec["data"]["s"])

    def test_12_search_snippet_truncation(self):
        """Verify snippet is truncated to 120 chars."""
        long_line = "A" * 200
        self.db.upsert_files([("long.txt", "repo1", 0, 0, long_line, 0)])
        
        res = execute_search({"query": "AAAA"}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        snippet = data["records"][0]["data"]["s"]
        self.assertLessEqual(len(snippet), 120)

    def test_13_search_line_parsing(self):
        """Verify line number is parsed from snippet L<N>:."""
        # Note: snippet_around in search_engine adds "L1:" prefix
        content = "target"
        self.db.upsert_files([("lines.txt", "repo1", 0, 0, content, 0)])
        
        res = execute_search({"query": "target"}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        rec = data["records"][0]
        # Should detect line 1 for single line content
        self.assertEqual(rec["data"]["line"], "1")

    def test_14_search_limit_clamping(self):
        """Verify search limit capped at 20."""
        files = [(f"f{i}.txt", "repo1", 0, 0, "match me", 0) for i in range(30)]
        self.db.upsert_files(files)
        
        res = execute_search({"query": "match", "limit": 100}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        # 'limit' is not in search header spec, only returned
        self.assertEqual(len(data["records"]), 20)
        self.assertEqual(data["header"]["returned"], "20")

    def test_15_search_total_mode_exact(self):
        """Verify total_mode=exact in header."""
        self.db.upsert_files([("a", "r", 0, 0, "q", 0)])
        res = execute_search({"query": "q"}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        self.assertEqual(data["header"]["total_mode"], "exact")
        self.assertEqual(data["header"]["total"], "1")

    def test_16_search_total_mode_approx(self):
        """Verify total_mode=approx handling (using Regex to force approx)."""
        # Regex search in search.py sets total_mode="approx"
        self.db.upsert_files([("a", "r", 0, 0, "pattern", 0)])
        res = execute_search({"query": "pat.*", "use_regex": True}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertEqual(data["header"]["total_mode"], "approx")
        # Total is omitted or -1 in approx mode usually, or count of hits if small
        pass

    def test_17_search_empty(self):
        """Verify search with no results."""
        res = execute_search({"query": "nothing"}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        self.assertEqual(data["header"]["returned"], "0")
        self.assertEqual(len(data["records"]), 0)

    # --- 6. Repo Candidates Tests ---

    def test_18_repo_candidates(self):
        """Verify repo_candidates returns r: records."""
        self.db.upsert_files([("f", "my_repo", 0, 0, "term", 0)])
        res = execute_repo_candidates({"query": "term"}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertEqual(data["tool"], "repo_candidates")
        rec = data["records"][0]
        self.assertEqual(rec["kind"], "r")
        self.assertEqual(rec["data"]["repo"], "my_repo")
        self.assertIn("score", rec["data"])

    def test_19_repo_candidates_limit(self):
        """Verify repo_candidates limit 5."""
        files = [(f"f{i}", f"repo{i}", 0, 0, "term", 0) for i in range(10)]
        self.db.upsert_files(files)
        
        res = execute_repo_candidates({"query": "term", "limit": 10}, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        
        self.assertLessEqual(len(data["records"]), 5)

    # --- 7. Legacy JSON Tests ---

    def test_20_legacy_json_mode(self):
        """Verify DECKARD_FORMAT=json returns JSON."""
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            self.db.upsert_files([("src/main.py", "repo1", 0, 0, "", 0)])
            res = execute_list_files({"repo": "repo1"}, self.db, self.logger, [])
            
            # Should be valid JSON
            data = json.loads(res["content"][0]["text"])
            self.assertIn("files", data)
            self.assertEqual(data["files"][0]["path"], "src/main.py")

    def test_21_search_legacy_json_structure(self):
        """Verify search in JSON mode preserves structure."""
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            self.db.upsert_files([("f", "r", 0, 0, "q", 0)])
            res = execute_search({"query": "q"}, self.db, self.logger, [])
            data = json.loads(res["content"][0]["text"])
            
            self.assertIn("results", data)
            self.assertEqual(data["results"][0]["path"], "f")
            # Verify no PACK1 artifacts
            self.assertFalse(res["content"][0]["text"].startswith("PACK1"))

    # --- 8. Coverage Boosters (Edge Cases) ---

    def test_22_search_edge_cases(self):
        """Cover search.py: empty query, workspace scope, docs type, invalid numbers."""
        # 1. Empty query
        res = execute_search({"query": ""}, self.db, self.logger, [])
        self.assertTrue(res["isError"])
        
        # 2. Workspace scope & docs type & invalid numbers
        # Use a real file for search
        self.db.upsert_files([("doc.md", "repo1", 0, 0, "content", 0)])
        args = {
            "query": "content",
            "scope": "workspace",
            "type": "docs",
            "limit": "invalid",
            "offset": "invalid",
            "context_lines": "invalid"
        }
        res = execute_search(args, self.db, self.logger, [])
        data = parse_pack1(res["content"][0]["text"])
        self.assertEqual(data["header"]["returned"], "1")

    def test_23_util_encoding_robustness(self):
        """Cover escaped characters in _util.py and error handling in mcp_response."""
        from mcp.tools._util import pack_encode_text, mcp_response
        
        # Text with quotes and backslashes
        text = 'Hello "World" \\ Path'
        encoded = pack_encode_text(text)
        # Current implementation uses urllib.parse.quote
        import urllib.parse
        self.assertEqual(encoded, urllib.parse.quote(text, safe=""))
        
        # mcp_response with error inside builder
        def error_builder():
            raise ValueError("Simulated error")
        
        res = mcp_response("test", error_builder, lambda: {})
        self.assertTrue(res.get("isError"))
        # Error message is URL-encoded in PACK1
        self.assertIn("Simulated%20error", res["content"][0]["text"])

    def test_24_search_line_num_fallback(self):
        """Cover case where line number cannot be parsed from snippet."""
        from unittest.mock import MagicMock
        from app.models import SearchHit
        
        mock_db = MagicMock()
        hit = SearchHit(repo="r1", path="p1", score=1.0, hit_reason="r", snippet="No line number here")
        # db.search_v2 returns (hits, meta_dict)
        mock_db.search_v2.return_value = ([hit], {"total": 1, "total_mode": "exact"})
        mock_db.get_index_status.return_value = {}
        mock_db.get_repo_stats.return_value = []

        res = execute_search({"query": "test"}, mock_db, self.logger, [])
        # Should default to line=0 (PACK1 uses k=v for record fields)
        self.assertIn("line=0", res["content"][0]["text"])

    def test_25_status_details(self):
        """Cover status.py indexing state and details=True."""
        from unittest.mock import MagicMock
        from mcp.tools.status import execute_status
        
        mock_db = MagicMock()
        mock_indexer = MagicMock()
        mock_cfg = MagicMock()
        
        mock_indexer.status.index_ready = True
        mock_indexer.status.last_scan_ts = 12345
        mock_indexer.status.scanned_files = 100
        mock_indexer.status.indexed_files = 50
        mock_indexer.status.errors = 0
        
        mock_db.fts_enabled = True
        mock_db.get_repo_stats.return_value = {"repo1": 10}
        
        mock_cfg.include_ext = [".py"]
        mock_cfg.max_file_bytes = 1000
        
        res = execute_status(
            {"details": True}, 
            mock_indexer, mock_db, mock_cfg, 
            "/root", "1.0.0", self.logger
        )
        text = res["content"][0]["text"]
        self.assertIn("m:indexed_files=50", text)
        self.assertIn("m:repo_repo1=10", text)

    def test_26_util_full_coverage(self):
        """Cover missed lines in _util.py: single_value, hints, JSON error, mcp_json."""
        from mcp.tools._util import pack_line, pack_error, ErrorCode, mcp_response, mcp_json
        
        # 1. pack_line with single_value
        line = pack_line("k", single_value="val")
        self.assertEqual(line, "k:val")
        
        # 2. pack_error with hints and trace
        err = pack_error("tool", ErrorCode.INTERNAL, "msg", hints=["h1"], trace="stack")
        self.assertIn("hint=h1", err)
        self.assertIn("trace=stack", err)
        
        # 3. JSON mode error handling in mcp_response
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            def error_builder():
                raise ValueError("JSON Error")
            
            res = mcp_response("test", lambda: "", error_builder)
            self.assertTrue(res["isError"])
            self.assertEqual(res["error"]["message"], "JSON Error")
            
        # 4. mcp_json direct usage
        res = mcp_json({"key": "val"})
        self.assertIn("key", res)
        self.assertIn('"key":"val"', res["content"][0]["text"])

    def test_27_legacy_json_details(self):
        """Cover legacy JSON specific logic (docstrings, approx mode)."""
        from app.models import SearchHit
        
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            # Hit with docstring
            hit = SearchHit(
                repo="r", path="p", score=1, snippet="s", hit_reason="h",
                docstring="Line1\nLine2\nLine3\nLine4"
            )
            # Mocking db search to return this hit
            # We need to mock search_v2 via the db object passed to execute_search
            # But execute_search defines build_json internally calling run_search
            
            # Since we can't easily inject hits into run_search without mocking db.search_v2
            # Force mock replacement
            self.db.search_v2 = MagicMock(return_value=([hit], {"total": 100, "total_mode": "approx", "total_scanned": 1000}))
            
            # Force approx mode logic in build_json
            # total_mode comes from db_meta
            
            res = execute_search({"query": "q", "limit": 10}, self.db, self.logger, [])
            data = json.loads(res["content"][0]["text"])
            
            # Check docstring truncation (3 lines + ...)
            self.assertIn("docstring", data["results"][0])
            self.assertIn("...", data["results"][0]["docstring"])
            
            # Check total_mode approx warnings
            self.assertEqual(data["total_mode"], "approx")
            self.assertTrue(any("approximate" in w for w in data["warnings"]))

    def test_28_argument_parsing_fallbacks(self):
        """Cover ValueError/TypeError in argument parsing for list_files and repo_candidates."""
        # 1. list_files bad limit
        res = execute_list_files({"repo": "r", "limit": "bad"}, self.db, self.logger, [])
        # Should default to limit 100 (or whatever default) and not crash
        self.assertFalse(res.get("isError"))
        
        # 2. repo_candidates bad limit and empty query
        res = execute_repo_candidates({"query": "", "limit": "bad"}, self.db, self.logger, [])
        # Empty query -> Error
        self.assertTrue(res.get("isError"))
        self.assertIn("Error: query is required", res["content"][0]["text"])

if __name__ == "__main__":
    unittest.main()
