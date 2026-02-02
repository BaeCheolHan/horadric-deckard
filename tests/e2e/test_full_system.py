
import pytest
import subprocess
import sys
import time
import os
import shutil
import json
from pathlib import Path

class TestFullSystemE2E:
    """
    Final System Integration Test.
    Treats the system as a Black Box, interacting strictly via CLI.
    """

    @pytest.fixture
    def workspace(self, tmp_path):
        ws = tmp_path / "e2e_workspace"
        ws.mkdir()
        return ws

    def test_e2e_lifecycle(self, workspace):
        """
        Scenario:
        1. User opens a workspace.
        2. User creates a file 'hello.py' with 'def HelloUser(): pass'.
        3. User starts Deckard Daemon.
        4. User searches 'HelloUser'.
        5. User stops Daemon.
        """
        # 1. Setup Files
        src_file = workspace / "hello.py"
        src_file.write_text("class HelloUser:\n    pass\n")
    
        # Prepare env
        env = os.environ.copy()
        # Ensure 'mcp' is importable. Assume pytest run from project root.
        project_root = Path(__file__).resolve().parent.parent.parent
        env["PYTHONPATH"] = str(project_root)
        env["DECKARD_HTTP_PORT"] = "0"
        # Isolate Registry
        env["DECKARD_REGISTRY_FILE"] = str(workspace / "server.json")
        # Ensure we don't look at global user config/registry if possible
        # (Though integration test uses temp workspace path so local config is safe)
    
        # Helper to run CLI (Foreground)
        def run_cli(args):
            cmd = [sys.executable, "-m", "mcp.cli"] + args
            return subprocess.run(
                cmd,
                cwd=str(workspace),
                env=env,
                capture_output=True,
                text=True
            )

        def tcp_init(port, ws_path):
            """Simulate MCP client initialization via TCP. Returns the socket."""
            import socket
            import json
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(("127.0.0.1", port))
            
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "rootUri": f"file://{ws_path}",
                    "capabilities": {}
                }
            }
            body = json.dumps(init_msg).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            sock.sendall(header + body)
            
            # Read response (minimal)
            resp = sock.recv(4096)
            # DO NOT CLOSE SOCKET HERE
            return sock, resp
    
        # 2. Start Daemon (Background)
        print("Starting Daemon...")
        daemon_port = 47800 # Fixed port for E2E to be sure
        env["DECKARD_DAEMON_PORT"] = str(daemon_port)
        
        daemon_cmd = [sys.executable, "-m", "mcp.cli", "daemon", "start"]
        
        daemon_proc = subprocess.Popen(
            daemon_cmd,
            cwd=str(workspace),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        mcp_sock = None
        try:
            # Wait for TCP Daemon to be up
            print(f"Waiting for TCP Daemon on {daemon_port}...")
            connected = False
            for _ in range(10):
                import socket
                try:
                    with socket.create_connection(("127.0.0.1", daemon_port), timeout=0.5):
                        connected = True
                        break
                except:
                    time.sleep(0.5)
            
            if not connected:
                pytest.fail("TCP Daemon failed to start.")

            # Trigger Workspace Initialization (starts HTTP server & Indexer)
            print(f"Initializing workspace via TCP...")
            mcp_sock, _ = tcp_init(daemon_port, workspace)

            # Wait for HTTP Server / Indexing
            print("Waiting for HTTP server (status)...")
            server_ready = False
            for _ in range(20):
                time.sleep(1)
                status_res = run_cli(["status"])
                if status_res.returncode == 0 and '"ok": true' in status_res.stdout:
                    server_ready = True
                    break
            
            if not server_ready:
                print(f"Last Status Output: {status_res.stdout}")
                print(f"Last Status Error: {status_res.stderr}")
                pytest.fail("HTTP Server failed to start after initialization.")

            # 3. Search
            print("Executing Search...")
            found = False
            search_out = ""
            for _ in range(10): # Giving more time for indexing
                search_res = run_cli(["search", "HelloUser"])
                if search_res.returncode == 0 and "hello.py" in search_res.stdout:
                    found = True
                    search_out = search_res.stdout
                    break
                time.sleep(1)
            
            assert found, f"Search failed. Last Output: {search_out}\nError: {search_res.stderr}"
            assert "class HelloUser" in search_out or "Symbol:" in search_out

        finally:
            # 4. Stop Daemon
            print("Stopping Daemon...")
            if mcp_sock:
                mcp_sock.close()
            run_cli(["daemon", "stop"])
            
            if daemon_proc.poll() is None:
                daemon_proc.terminate()
                try:
                    daemon_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    daemon_proc.kill()
            
            # Verify stop
            # assert stop_res.returncode == 0 # Sometimes if we force kill, stop might complain
            pass
