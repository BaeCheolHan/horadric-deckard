import unittest
import tempfile
import os
import shutil
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.db import LocalSearchDB
from app.indexer import Indexer
from app.config import Config
from mcp.tools.list_files import execute_list_files
from mcp.tools.repo_candidates import execute_repo_candidates
from tests.pack1_util import parse_pack1

class TestIntegrationPortability(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir) / "ws"
        self.workspace.mkdir()
        self.db_path = str(self.workspace / "test.db")
        self.db = LocalSearchDB(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    def test_list_files_complex_filter_pack1(self):
        """Case 3: list_files with multiple filters (PACK1)"""
        ts = int(time.time())
        self.db.upsert_files([
            ("repo1/src/main.py", "repo1", 0, 0, "content", ts),
            ("repo1/src/utils.ts", "repo1", 0, 0, "content", ts),
            ("repo1/docs/readme.md", "repo1", 0, 0, "content", ts),
            ("repo2/src/main.py", "repo2", 0, 0, "content", ts),
        ])
        
        args = {
            "repo": "repo1",
            "file_types": ["py"],
            "path_pattern": "src"
        }
        result = execute_list_files(args, self.db, MagicMock())
        data = parse_pack1(result["content"][0]["text"])
        
        # In PACK1, records are under "records"
        paths = [r["value"] for r in data["records"] if r["kind"] == "p"]
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], "repo1/src/main.py")
        self.assertEqual(data["header"]["returned"], "1")

    def test_list_files_legacy_json(self):
        """Verify legacy JSON mode still works via env var"""
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            ts = int(time.time())
            self.db.upsert_files([("test.py", "repo1", 0, 0, "content", ts)])
            args = {"repo": "repo1"}
            result = execute_list_files(args, self.db, MagicMock())
            data = json.loads(result["content"][0]["text"])
            self.assertIn("files", data)
            self.assertEqual(data["files"][0]["path"], "test.py")

    def test_repo_candidates_scoring_pack1(self):
        """Case 4: repo_candidates scoring logic (PACK1)"""
        ts = int(time.time())
        self.db.upsert_files([
            ("f1.txt", "repo_high", 0, 0, "target keyword", ts),
            ("f2.txt", "repo_high", 0, 0, "target keyword", ts),
            ("f3.txt", "repo_low", 0, 0, "target keyword", ts),
        ])
        
        args = {"query": "target"}
        result = execute_repo_candidates(args, self.db)
        data = parse_pack1(result["content"][0]["text"])
        
        candidates = [r["data"] for r in data["records"] if r["kind"] == "r"]
        self.assertEqual(candidates[0]["repo"], "repo_high")
        self.assertIn("Low match", candidates[0]["reason"])

    def test_indexer_ai_safety_net(self):
        """Case 5: Indexer AI Safety Net (force re-index)"""
        test_file = self.workspace / "safe.txt"
        test_file.write_text("initial")
        mtime = int(time.time())
        os.utime(test_file, (mtime, mtime))
        
        cfg = Config(
            workspace_roots=[str(self.workspace)],
            workspace_root=str(self.workspace),
            server_host="127.0.0.1", server_port=47777,
            scan_interval_seconds=180, snippet_max_lines=5,
            max_file_bytes=800000, db_path=self.db_path,
            include_ext=[".txt"], include_files=[],
            exclude_dirs=[], exclude_globs=[],
            redact_enabled=True, commit_batch_size=500
        )
        
        indexer = Indexer(cfg, self.db)
        indexer.scan_once()
        first_indexed = indexer.status.indexed_files
        
        # Re-scan without changing file: should still index within safety window
        indexer.scan_once()
        indexer.stop()
        self.assertGreater(indexer.status.indexed_files, first_indexed)

    def test_server_json_port_tracking(self):
        """Case 2: server.json tracks actual port"""
        import app.main
        with patch("app.main.serve_forever", return_value=(MagicMock(), 48888)), \
             patch("app.main.Config.load", return_value=MagicMock(server_port=47777, db_path=self.db_path, server_host="127.0.0.1")):
            
            with patch("app.main.WorkspaceManager.resolve_workspace_root", return_value=str(self.workspace)), \
                 patch("app.main.Indexer"), patch("app.main.LocalSearchDB"), \
                 patch("app.main.time.sleep", side_effect=InterruptedError):
                
                try:
                    app.main.main()
                except (InterruptedError, SystemExit):
                    pass
                
                server_json = Path(self.workspace) / ".codex" / "tools" / "deckard" / "data" / "server.json"
                self.assertTrue(server_json.exists(), f"server.json missing at {server_json}")
                info = json.loads(server_json.read_text())
                self.assertEqual(info["port"], 48888)

if __name__ == "__main__":
    unittest.main()
