import json
import os
import subprocess
import time
import socket
import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

class TestDaemonCliIntegration:
    
    @pytest.fixture
    def test_env(self, tmp_path):
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["USERPROFILE"] = str(fake_home)
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        env["SARI_DAEMON_AUTOSTART"] = "1"
        env["SARI_DAEMON_IDLE_SEC"] = "60" # Default long enough
        env["SARI_DAEMON_HEARTBEAT_SEC"] = "1"
        
        return env

    @pytest.fixture
    def workspace(self, tmp_path):
        ws = tmp_path / "test_ws"
        ws.mkdir()
        (ws / ".sari").mkdir(parents=True, exist_ok=True)
        return str(ws.expanduser().resolve())

    def test_daemon_lifecycle(self, workspace, test_env):
        test_env["SARI_WORKSPACE_ROOT"] = workspace
        port = "47891"
        
        try:
            subprocess.run(
                ["python3", "-m", "sari.mcp.cli", "daemon", "start", "-d", "--daemon-port", port],
                env=test_env, check=True
            )
            time.sleep(2.0)
            
            result = subprocess.run(
                ["python3", "-m", "sari.mcp.cli", "daemon", "status", "--daemon-port", port],
                env=test_env, capture_output=True, text=True
            )
            assert "Running" in result.stdout
            
            subprocess.run(
                ["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", port],
                env=test_env, check=True
            )
            time.sleep(0.5)
            
            result = subprocess.run(
                ["python3", "-m", "sari.mcp.cli", "daemon", "status", "--daemon-port", port],
                env=test_env, capture_output=True, text=True
            )
            assert "Stopped" in result.stdout
            
        finally:
            subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", port], env=test_env)

    def test_server_auto_proxy_mode(self, workspace, test_env):
        test_env["SARI_WORKSPACE_ROOT"] = workspace
        port = "47894"
        test_env["SARI_DAEMON_PORT"] = port
        
        subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "start", "-d", "--daemon-port", port], env=test_env, check=True)
        time.sleep(2.5)
        
        try:
            init_req = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}})
            test_env["SARI_DEV_JSONL"] = "1"
            
            proc = subprocess.Popen(
                ["python3", "-m", "sari.mcp.server"],
                env=test_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            
            stdout, stderr = proc.communicate(input=(init_req + "\n").encode(), timeout=10)
            stdout_str = stdout.decode(errors='ignore')
            
            assert '"result":' in stdout_str
            
        finally:
            subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", port], env=test_env)

    def test_daemon_idle_auto_stop(self, workspace, test_env):
        test_env["SARI_WORKSPACE_ROOT"] = workspace
        port = "47896"
        test_env["SARI_DAEMON_IDLE_SEC"] = "2"
        test_env["SARI_DAEMON_IDLE_WITH_ACTIVE"] = "1"
        
        subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "start", "-d", "--daemon-port", port], env=test_env, check=True)
        time.sleep(2.0)
        
        try:
            result = subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "status", "--daemon-port", port], env=test_env, capture_output=True, text=True)
            assert "Running" in result.stdout
            
            time.sleep(5.0)
            
            result = subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "status", "--daemon-port", port], env=test_env, capture_output=True, text=True)
            assert "Stopped" in result.stdout
            
        finally:
            subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", port], env=test_env)