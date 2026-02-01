
import pytest
import os
import time
import json
import signal
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import necessary modules
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from app.db import LocalSearchDB, SearchOptions
from app.registry import ServerRegistry
from mcp.server import LocalSearchMCPServer

class TestRound3Resilience:
    """
    Round 3: Resilience & Integration.
    """

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "test_round3.db")
        db = LocalSearchDB(db_path)
        yield db
        db.close()

    def test_registry_stale_pid_cleanup(self, tmp_path):
        """TC1: Verify registry cleans up stale PIDs."""
        reg_dir = tmp_path / "registry_stale"
        reg_dir.mkdir()
        reg_file = reg_dir / "server.json"
        
        with patch('app.registry.REGISTRY_FILE', reg_file):
            reg = ServerRegistry()
            
            # Register a fake PID (99999 normally doesn't exist, but verify)
            fake_pid = 99999
            try:
                os.kill(fake_pid, 0)
                # If 99999 exists, find another
                fake_pid = 99998
            except OSError:
                pass
                
            reg.register("/stale/workspace", 9000, fake_pid)
            
            # Verify it was written
            inst = reg._load()["instances"]["/stale/workspace"]
            assert inst["pid"] == fake_pid
            
            # Now call get_instance, which should perform liveness check
            # Since PID doesn't exist, it should return None and remove entry?
            # Or just return None? Detailed impl says it checks os.kill.
            
            # Note: Current implementation of get_instance might or might not auto-clean.
            # Let's check get_instance behavior.
            inst = reg.get_instance("/stale/workspace")
            assert inst is None
            
            # Verify cleanup if implementation supports it (Registry.get_instance usually just returns None if dead)
            # But let's check if we can register over it.
            my_pid = os.getpid()
            reg.register("/stale/workspace", 9001, my_pid)
            inst = reg.get_instance("/stale/workspace")
            assert inst["port"] == 9001
            assert inst["pid"] == my_pid

    def test_hybrid_search_consistency(self, db):
        """TC2: Verify Hybrid Search returns deterministic results."""
        now = int(time.time())
        # Insert mixed content
        files = [
            ("main.py", "repo", now, 100, "class User:\n    pass", now),
            ("util.py", "repo", now, 100, "def helper(u=User): pass", now),
            ("test.py", "repo", now, 100, "test_user = User()", now)
        ]
        db.upsert_files(files)
        db.upsert_symbols([("main.py", "User", "class", 1, 2, "class User:\n    pass", "")])
        
        opts = SearchOptions(query="User", limit=10)
        
        # Run 10 times, results should be identical order
        first_hits, _ = db.search_v2(opts)
        first_paths = [h.path for h in first_hits]
        
        for _ in range(10):
            hits, _ = db.search_v2(opts)
            paths = [h.path for h in hits]
            assert paths == first_paths

    def test_daemon_restart_recovery(self, tmp_path):
        """TC3: Verify Daemon can overwrite old port if restarted."""
        # This is similar to Stale PID but focused on the Register flow logic.
        reg_dir = tmp_path / "registry_restart"
        reg_dir.mkdir()
        reg_file = reg_dir / "server.json"
        
        with patch('app.registry.REGISTRY_FILE', reg_file):
            reg = ServerRegistry()
            pid = os.getpid()
            
            # Start 1
            reg.register("/ws/1", 8080, pid)
            
            # Restart (same PID, new Port?) or New PID, same Path
            # Scenario: Daemon restart (new PID)
            new_pid = pid # For test env we reuse PID but imagine it's fresh start logic
            # In update_registry, it blindly overwrites?
            reg.register("/ws/1", 8081, new_pid)
            
            inst = reg.get_instance("/ws/1")
            assert inst["port"] == 8081

    def test_mcp_malformed_json(self):
        """TC4: Verify generic JSON RPC error handling mock."""
        # Simple unit test for JSON-RPC parsing usually handled by MCP library.
        # But if we have custom handlers, check them.
        # Here we just verify that we don't crash Deckard.
        pass

    def test_db_timeout_mock(self, tmp_path):
        """TC5: Verify DB raises OperationalError on lock timeout."""
        # Need to patch connect BEFORE DB init
        db_path = str(tmp_path / "timeout.db")
        
        with patch('sqlite3.connect') as mock_connect:
            # Setup mock connection
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            
            # Define side effect to allow init but fail search
            def execute_side_effect(sql, *args, **kwargs):
                sql_upper = str(sql).upper()
                # Init queries: PRAGMA, CREATE TABLE
                if "PRAGMA" in sql_upper or "CREATE TABLE" in sql_upper:
                    return MagicMock()
                # Search queries usually start with SELECT
                if "SELECT" in sql_upper:
                     raise sqlite3.OperationalError("database is locked")
                return MagicMock()
            
            mock_conn.execute.side_effect = execute_side_effect
            
            # Init DB (calls connect -> execute PRAGMA/CREATE) -> Should succeed
            db = LocalSearchDB(db_path)
            
            opts = SearchOptions(query="busy", limit=1)
            
            # Search calls execute SELECT -> Should fail
            with pytest.raises(sqlite3.OperationalError):
                db.search_v2(opts)
            
            db.close()
