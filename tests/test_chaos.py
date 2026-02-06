import json
import os
import time
import socket
import pytest
import subprocess
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

class TestChaosAndResilience:
    
    @pytest.fixture
    def chaos_env(self, tmp_path):
        fake_home = tmp_path / "chaos_home"
        fake_home.mkdir()
        
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "chaos_registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        env["SARI_DAEMON_AUTOSTART"] = "1"
        env["SARI_DAEMON_PORT"] = "48001"
        
        return env

    def test_chaos_stale_pid_recovery(self, chaos_env):
        pid_dir = Path(chaos_env["HOME"]) / ".local" / "share" / "sari"
        pid_dir.mkdir(parents=True, exist_ok=True)
        pid_file = pid_dir / "daemon.pid"
        pid_file.write_text("999999") 
        
        subprocess.run(
            ["python3", "-m", "sari.mcp.cli", "daemon", "start", "-d", "--daemon-port", "48001"],
            env=chaos_env, check=True
        )
        time.sleep(2.0)
        
        new_pid = int(pid_file.read_text().strip())
        assert new_pid != 999999
        
        status = subprocess.run(
            ["python3", "-m", "sari.mcp.cli", "daemon", "status", "--daemon-port", "48001"],
            env=chaos_env, capture_output=True, text=True
        )
        assert "Running" in status.stdout
        
        subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", "48001"], env=chaos_env)

    def test_chaos_registry_corruption(self, chaos_env):
        reg_file = Path(chaos_env["SARI_REGISTRY_FILE"])
        reg_file.parent.mkdir(parents=True, exist_ok=True)
        reg_file.write_text("THIS IS NOT JSON!!! CORRUPTED!!!")
        
        subprocess.run(
            ["python3", "-m", "sari.mcp.cli", "daemon", "start", "-d", "--daemon-port", "48002"],
            env=chaos_env, check=True
        )
        time.sleep(2.0)
        
        data = json.loads(reg_file.read_text())
        assert data["version"] == "2.0"
        
        subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", "48002"], env=chaos_env)

    def test_chaos_recursive_symlink(self, tmp_path, chaos_env):
        from sari.core.indexer.scanner import Scanner
        
        ws = tmp_path / "recursive_ws"
        ws.mkdir()
        sub = ws / "sub"
        sub.mkdir()
        loop = sub / "loop"
        try:
            os.symlink(ws, loop)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")
            
        cfg = MagicMock()
        cfg.exclude_dirs = []
        cfg.settings.FOLLOW_SYMLINKS = True 
        cfg.settings.MAX_DEPTH = 10 # Fix MagicMock comparison
        
        scanner = Scanner(cfg)
        entries = list(scanner.iter_file_entries(ws))
        assert len(entries) < 10

    def test_chaos_db_batch_partial_success(self, chaos_env):
        from sari.core.indexer.db_writer import DBWriter, DbTask
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db._write = mock_conn
        mock_conn.cursor.return_value = mock_cur
        
        writer = DBWriter(mock_db, max_batch=2)
        tasks = [
            DbTask(kind="upsert_files", rows=[("p1",)]),
            DbTask(kind="upsert_files", rows=[("p2",)])
        ]
        
        # Manually put tasks into the real queue to avoid task_done mismatch
        for t in tasks:
            writer.enqueue(t)
        
        commit_calls = []
        def mock_commit(): commit_calls.append("commit")
        mock_conn.commit.side_effect = mock_commit
        
        rollback_calls = []
        def mock_rollback(): rollback_calls.append("rollback")
        mock_conn.rollback.side_effect = mock_rollback

        with patch.object(writer, "_process_batch") as mock_proc:
            mock_proc.side_effect = [Exception("Locked"), {"files": 1, "files_paths": ["p1"]}, {"files": 1, "files_paths": ["p2"]}]
            
            # Don't mock the queue entirely, just control loop
            writer._stop.set()
            writer._run()
            
            assert len(rollback_calls) == 1
            assert len(commit_calls) == 2
            assert mock_proc.call_count == 3
