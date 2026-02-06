import json
import os
import time
import socket
import pytest
import subprocess
from pathlib import Path

class TestMultiWorkspaceIntegration:
    
    @pytest.fixture
    def multi_env(self, tmp_path):
        fake_home = tmp_path / "multi_home"
        fake_home.mkdir()
        
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "multi_registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        env["SARI_DAEMON_AUTOSTART"] = "1"
        env["SARI_DAEMON_PORT"] = "48100"
        
        return env

    def test_daemon_handles_multiple_workspaces(self, tmp_path, multi_env):
        ws_paths = []
        for i in range(3):
            ws = tmp_path / f"ws_{i}"
            ws.mkdir()
            (ws / ".sari").mkdir()
            (ws / f"file_{i}.txt").write_text(f"Content from WS {i}")
            ws_paths.append(str(ws.expanduser().resolve()))

        multi_env["SARI_WORKSPACE_ROOT"] = ws_paths[0]
        subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "start", "-d", "--daemon-port", "48100"], env=multi_env, check=True)
        time.sleep(2.0)
        
        try:
            def send_init(ws_path):
                init_req = json.dumps({"jsonrpc":"2.0","id":1, "method":"initialize","params":{"rootUri": f"file://{ws_path}"}})
                frame = f"Content-Length: {len(init_req)}\r\n\r\n{init_req}".encode()
                with socket.create_connection(("127.0.0.1", 48100)) as sock:
                    sock.sendall(frame)
                    resp = sock.recv(4096)
                    assert b'"result":' in resp

            send_init(ws_paths[1])
            send_init(ws_paths[2])
            
            time.sleep(3.0) 
            
            from sari.core.server_registry import ServerRegistry
            os.environ["SARI_REGISTRY_FILE"] = multi_env["SARI_REGISTRY_FILE"]
            registry = ServerRegistry()
            
            ports = []
            for ws in ws_paths:
                info = registry.get_workspace(ws)
                assert info is not None, f"WS {ws} not registered"
                assert info.get("http_port") is not None
                ports.append(info["http_port"])
            
            assert len(set(ports)) == 3, f"Ports should be unique: {ports}"
            
            for i, port in enumerate(ports):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    assert s.connect_ex(("127.0.0.1", port)) == 0, f"HTTP server for WS {i} at {port} not reachable"

        finally:
            subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", "48100"], env=multi_env)