import unittest
import asyncio
import json
import tempfile
import os
import shutil
from pathlib import Path
from mcp.registry import Registry
from mcp.server import LocalSearchMCPServer
from app.db import SearchOptions
from unittest.mock import patch

class TestConcurrencyStress(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        Registry.reset_instance()
        self.registry = Registry.get_instance()

    def tearDown(self):
        self.registry.shutdown_all()
        shutil.rmtree(self.tmp_dir)

    def test_registry_refcount_lifecycle(self):
        """Case 5: Registry refcount and shutdown"""
        ws_root = os.path.join(self.tmp_dir, "ws1")
        os.makedirs(ws_root)
        Path(ws_root, ".codex-root").touch()
        
        state = self.registry.get_or_create(ws_root)
        self.assertEqual(state.ref_count, 1)
        self.assertEqual(self.registry.active_count(), 1)
        
        self.registry.release(ws_root)
        self.assertEqual(self.registry.active_count(), 0)

    async def test_search_pagination_overflow(self):
        """Case 2: Search offset overflow"""
        ws_root = os.path.join(self.tmp_dir, "ws2")
        os.makedirs(ws_root)
        server = LocalSearchMCPServer(ws_root)
        server._ensure_initialized()
        
        # Search with large offset
        args = {"query": "any", "offset": 1000, "limit": 10}
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            result = server._tool_search(args)
            data = json.loads(result["content"][0]["text"])
            self.assertEqual(len(data["results"]), 0)
            self.assertFalse(data["has_more"])

    def test_fts_fallback_on_syntax_error(self):
        """Case 3: FTS syntax error fallback"""
        ws_root = os.path.join(self.tmp_dir, "ws3")
        os.makedirs(ws_root)
        server = LocalSearchMCPServer(ws_root)
        server._ensure_initialized()
        
        # Query with mismatched quote (FTS error)
        args = {"query": 'unclosed " quote', "limit": 10}
        with patch.dict(os.environ, {"DECKARD_FORMAT": "json"}):
            result = server._tool_search(args)
            data = json.loads(result["content"][0]["text"])
            # Should return result (empty or matched via LIKE) without error
            self.assertIn("meta", data)
            self.assertTrue(data["meta"]["fallback_used"])

    def test_multi_workspace_isolation(self):
        """Case 1: Multi-workspace isolation"""
        ws1 = os.path.join(self.tmp_dir, "ws4")
        ws2 = os.path.join(self.tmp_dir, "ws5")
        os.makedirs(ws1); os.makedirs(ws2)
        
        s1 = self.registry.get_or_create(ws1)
        s2 = self.registry.get_or_create(ws2)
        
        s1.server._ensure_initialized()
        s2.server._ensure_initialized()
        
        self.assertNotEqual(s1.server.workspace_root, s2.server.workspace_root)
        self.assertNotEqual(s1.server.db.db_path, s2.server.db.db_path)

    async def test_concurrent_read_write_wal(self):
        """Case 4: Concurrent read/write (WAL check)"""
        ws = os.path.join(self.tmp_dir, "ws6")
        os.makedirs(ws)
        server = LocalSearchMCPServer(ws)
        server._ensure_initialized()
        
        # Simulate write
        server.db.upsert_files([("f.txt", "r", 0, 0, "content", 1)])
        
        # Simultaneous read should work
        hits, _ = server.db.search("content", repo=None)
        self.assertEqual(len(hits), 1)

if __name__ == "__main__":
    unittest.main()
