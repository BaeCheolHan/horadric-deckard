import json
import os
import time
import socket
import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

class TestEmbeddedServer:
    
    @pytest.fixture
    def workspace(self, tmp_path):
        ws = tmp_path / "test_ws_embedded"
        ws.mkdir()
        (ws / ".sari").mkdir(parents=True, exist_ok=True)
        return str(ws.expanduser().resolve())

    @pytest.fixture
    def test_env(self, tmp_path):
        env = os.environ.copy()
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        return env

    def test_http_server_lifecycle(self, workspace, test_env):
        from sari.mcp.workspace_registry import Registry
        from sari.core.server_registry import ServerRegistry
        
        os.environ["SARI_REGISTRY_FILE"] = test_env["SARI_REGISTRY_FILE"]
        Registry._instance = None
        registry = Registry.get_instance()
        
        # 1. Create Session
        session = registry.get_or_create(workspace)
        port = session.http_port
        assert self._is_port_open(port)
        
        # Verify registered
        ws_info = ServerRegistry().get_workspace(workspace)
        assert ws_info is not None
        assert ws_info["http_port"] == port
        
        # 2. Release Session
        registry.release(workspace)
        time.sleep(1.0)
        
        # Verify port is CLOSED
        assert not self._is_port_open(port), f"Port {port} still open after release"
        
        # Verify UNREGISTERED
        ws_info_after = ServerRegistry().get_workspace(workspace)
        assert ws_info_after is None

    def test_multi_cli_single_http_server(self, workspace, test_env):
        # 1. Start a daemon
        test_env["SARI_WORKSPACE_ROOT"] = workspace
        test_env["SARI_DAEMON_PORT"] = "47991"
        
        subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "start", "-d", "--daemon-port", "47991"], env=test_env, check=True)
        time.sleep(2.0)
        
        try:
            from sari.core.server_registry import ServerRegistry
            os.environ["SARI_REGISTRY_FILE"] = test_env["SARI_REGISTRY_FILE"]
            ws_info = ServerRegistry().get_workspace(workspace)
            assert ws_info is not None
            original_port = ws_info.get("http_port")
            
            # 2. Run a second CLI process (Standalone)
            test_env["SARI_DEV_JSONL"] = "1"
            proc = subprocess.Popen(
                ["python3", "-m", "sari.mcp.server"],
                env=test_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            
            time.sleep(2.0)
            
            # Check registry again - http_port should NOT have changed (Daemon still owns it)
            ws_info_after = ServerRegistry().get_workspace(workspace)
            assert ws_info_after.get("http_port") == original_port
            
            # Send a request - should work via forwarding
            init_req = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}})
            stdout, stderr = proc.communicate(input=init_req + "\n", timeout=10)
            assert '"result":' in stdout
            
        finally:
            subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", "47991"], env=test_env)

    def _is_port_open(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex(("127.0.0.1", port)) == 0
