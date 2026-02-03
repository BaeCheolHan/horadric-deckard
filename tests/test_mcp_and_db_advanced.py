import unittest
import json
import os
import tempfile
import shutil
import sqlite3
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
from mcp.session import Session
from app.workspace import WorkspaceManager

class TestMCPAndDBAdvanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir) / "ws"
        self.workspace.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    async def test_notification_no_response(self):
        """Verify that notifications (no id) do not produce a response."""
        reader = asyncio.StreamReader()
        writer = MagicMock()
        session = Session(reader, writer)
        
        # 'initialized' is a notification in MCP
        notification = {
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {}
        }
        
        # Setup session with a mock shared_state
        session.shared_state = MagicMock()
        
        await session.process_request(notification)
        
        # writer.write should not be called because there's no response for a notification
        # EXCEPT for the initialize response which we are skipping here.
        # process_request for initialized calls shared_state.server.handle_initialized
        self.assertFalse(writer.write.called)

    def test_workspace_priority_env(self):
        """Verify ENV var takes precedence for workspace root."""
        old_cwd = os.getcwd()
        try:
            env_ws = Path(self.tmp_dir) / "env_ws"
            env_ws.mkdir()

            with patch.dict("os.environ", {"DECKARD_WORKSPACE_ROOT": str(env_ws)}):
                detected = WorkspaceManager.resolve_workspace_root()
                self.assertEqual(detected, str(env_ws.absolute()))
        finally:
            os.chdir(old_cwd)

    def test_db_wal_mode(self):
        """Verify SQLite is running in WAL mode."""
        from app.db import LocalSearchDB
        db_path = str(Path(self.tmp_dir) / "wal_test.db")
        db = LocalSearchDB(db_path)
        
        # Check journal_mode
        conn = sqlite3.connect(db_path)
        res = conn.execute("PRAGMA journal_mode").fetchone()
        self.assertEqual(res[0].lower(), "wal")
        
        db.close()
        conn.close()

if __name__ == "__main__":
    unittest.main()
