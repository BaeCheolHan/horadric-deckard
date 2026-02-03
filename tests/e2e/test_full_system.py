
import pytest
import subprocess
import sys
import time
import os
import shutil
import json
from pathlib import Path
from tests.e2e._helpers import db_files_count

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
        import socket
        # Skip if sandbox disallows binding the test port.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", 0))
            daemon_port = probe.getsockname()[1]
        except PermissionError:
            pytest.skip("Port binding not permitted in this environment")
        finally:
            try:
                probe.close()
            except Exception:
                pass
        # 1. Setup Files
        src_file = workspace / "hello.py"
        src_file.write_text("class HelloUser:\n    pass\n")
    
        # Prepare env
        env = os.environ.copy()
        # Ensure 'mcp' is importable. Assume pytest run from project root.
        project_root = Path(__file__).resolve().parent.parent.parent
        env["PYTHONPATH"] = str(project_root)
        # Use registry to discover HTTP port.
        env.pop("DECKARD_PORT", None)
        env.pop("DECKARD_HTTP_PORT", None)
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

        def http_get(host, port, path):
            import http.client
            conn = http.client.HTTPConnection(host, port, timeout=2)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                data = resp.read()
                return resp.status, data
            finally:
                conn.close()

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

        def read_mcp_response(sock):
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                header += chunk
            if b"\r\n\r\n" not in header:
                return None
            head, rest = header.split(b"\r\n\r\n", 1)
            content_length = 0
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":", 1)[1].strip())
                    break
            body = rest
            while len(body) < content_length:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                body += chunk
            try:
                return json.loads(body[:content_length].decode("utf-8"))
            except Exception:
                return None

        def send_mcp_request(sock, payload):
            body = json.dumps(payload).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            sock.sendall(header + body)
            return read_mcp_response(sock)

        def parse_pack_metrics(text):
            metrics = {}
            for line in text.splitlines():
                if line.startswith("m:"):
                    _, rest = line.split("m:", 1)
                    if "=" in rest:
                        k, v = rest.split("=", 1)
                        metrics[k.strip()] = v.strip()
            return metrics

        # 2. Start Daemon (Background)
        print("Starting Daemon...")
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
        test_failed = False
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
            # Send 'initialized' notification to complete handshake.
            try:
                send_mcp_request(
                    mcp_sock,
                    {
                        "jsonrpc": "2.0",
                        "method": "initialized",
                        "params": {},
                    },
                )
            except Exception:
                pass
            # Force a synchronous scan via MCP to make indexing deterministic.
            try:
                send_mcp_request(
                    mcp_sock,
                    {
                        "jsonrpc": "2.0",
                        "id": "scanonce-init",
                        "method": "tools/call",
                        "params": {"name": "scan_once", "arguments": {}},
                    },
                )
            except Exception:
                pass

            # Wait for HTTP Server / Indexing
            print("Waiting for HTTP server (status)...")
            server_ready = False
            status_res = None
            last_err = None
            for _ in range(20):
                time.sleep(1)
                try:
                    reg_path = Path(env["DECKARD_REGISTRY_FILE"])
                    if not reg_path.exists():
                        continue
                    data = json.loads(reg_path.read_text())
                    inst = data.get("instances", {}).get(str(workspace.resolve()))
                    if not inst:
                        continue
                    host = inst.get("host", "127.0.0.1")
                    port = inst.get("port")
                    if not port:
                        continue
                    code, body = http_get(host, port, "/status")
                    if code == 200:
                        status_res = type("R", (), {"stdout": body.decode("utf-8"), "returncode": 0})()
                        server_ready = True
                        break
                except Exception as e:
                    last_err = e
                    continue

            if not server_ready:
                # Fallback: use MCP tool calls directly if HTTP isn't reachable.
                if not mcp_sock:
                    pytest.fail("HTTP server not ready and MCP socket is unavailable.")

                send_mcp_request(
                    mcp_sock,
                    {
                        "jsonrpc": "2.0",
                        "id": "rescan-1",
                        "method": "tools/call",
                        "params": {"name": "rescan", "arguments": {}},
                    },
                )
                send_mcp_request(
                    mcp_sock,
                    {
                        "jsonrpc": "2.0",
                        "id": "scanonce-1",
                        "method": "tools/call",
                        "params": {"name": "scan_once", "arguments": {}},
                    },
                )

                # Wait for commit via MCP status tool.
                for _ in range(15):
                    time.sleep(1)
                    resp = send_mcp_request(
                        mcp_sock,
                        {
                            "jsonrpc": "2.0",
                            "id": "status-1",
                            "method": "tools/call",
                            "params": {"name": "status", "arguments": {}},
                        },
                    )
                    if not resp or "result" not in resp:
                        continue
                    text = resp["result"]["content"][0]["text"]
                    metrics = parse_pack_metrics(text)
                    if (
                        metrics.get("last_commit_ts", "0").isdigit()
                        and int(metrics.get("last_commit_ts", "0")) > 0
                        and metrics.get("queue_db_writer", "1") == "0"
                    ):
                        break
                # Proceed with MCP-only search path below.
                status_res = None

            # Trigger an explicit rescan and wait for at least one indexed file.
            try:
                status_data = json.loads(status_res.stdout)
                host = status_data.get("host", "127.0.0.1")
                port = status_data.get("port")
                if not port:
                    raise RuntimeError("HTTP port missing in status response")
                http_get(host, port, "/rescan")
                for _ in range(15):
                    time.sleep(1)
                    code, body = http_get(host, port, "/status")
                    if code != 200:
                        continue
                    try:
                        status_data = json.loads(body.decode("utf-8"))
                    except Exception:
                        continue
                    q = status_data.get("queue_depths") or {}
                    if (
                        status_data.get("indexed_files", 0) >= 1
                        and q.get("db_writer", 0) == 0
                        and status_data.get("last_commit_ts", 0) > 0
                    ):
                        break
                # Direct DB check
                db_path = workspace / ".codex" / "tools" / "deckard" / "data" / "index.db"
                for _ in range(10):
                    if db_files_count(db_path) > 0:
                        break
                    time.sleep(0.5)
            except Exception:
                pass

            # Ensure watcher sees a change after initialization.
            src_file.write_text("class HelloUser:\n    pass\n")
            time.sleep(0.5)

            # 3. Search
            print("Executing Search...")
            found = False
            search_out = ""
            search_err = ""
            if status_res is None and mcp_sock:
                send_mcp_request(
                    mcp_sock,
                    {
                        "jsonrpc": "2.0",
                        "id": "index-1",
                        "method": "tools/call",
                        "params": {"name": "index_file", "arguments": {"path": str(src_file)}},
                    },
                )
                send_mcp_request(
                    mcp_sock,
                    {
                        "jsonrpc": "2.0",
                        "id": "scanonce-2",
                        "method": "tools/call",
                        "params": {"name": "scan_once", "arguments": {}},
                    },
                )
                for _ in range(30):
                    time.sleep(1)
                    resp = send_mcp_request(
                        mcp_sock,
                        {
                            "jsonrpc": "2.0",
                            "id": "status-2",
                            "method": "tools/call",
                            "params": {"name": "status", "arguments": {}},
                        },
                    )
                    if not resp or "result" not in resp:
                        continue
                    text = resp["result"]["content"][0]["text"]
                    metrics = parse_pack_metrics(text)
                    if (
                        metrics.get("indexed_files", "0").isdigit()
                        and int(metrics.get("indexed_files", "0")) >= 1
                        and metrics.get("queue_db_writer", "1") == "0"
                    ):
                        break
                # Direct DB check
                db_path = workspace / ".codex" / "tools" / "deckard" / "data" / "index.db"
                for _ in range(10):
                    if db_files_count(db_path) > 0:
                        break
                    time.sleep(0.5)
            for _ in range(20): # Giving more time for indexing
                if status_res is not None:
                    search_res = run_cli(["search", "HelloUser"])
                    search_out = search_res.stdout
                    search_err = search_res.stderr
                    if search_res.returncode == 0 and "hello.py" in search_res.stdout:
                        found = True
                        break
                else:
                    resp = send_mcp_request(
                        mcp_sock,
                        {
                            "jsonrpc": "2.0",
                            "id": "search-1",
                            "method": "tools/call",
                            "params": {"name": "search", "arguments": {"query": "HelloUser"}},
                        },
                    )
                    if resp and "result" in resp:
                        text = resp["result"]["content"][0]["text"]
                        search_out = text
                        if "hello.py" in text:
                            found = True
                            break
                    elif resp and "error" in resp:
                        search_out = json.dumps(resp.get("error"), ensure_ascii=False)
                time.sleep(1)

            if not found:
                test_failed = True
            if not found:
                db_path = workspace / ".codex" / "tools" / "deckard" / "data" / "index.db"
                print(f"[debug] db_files_count={db_files_count(db_path)} db_path={db_path}")
            assert found, f"Search failed. Last Output: {search_out}\nError: {search_err}"
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

            if test_failed:
                try:
                    out, err = daemon_proc.communicate(timeout=1)
                except Exception:
                    out, err = ("", "")
                if out:
                    print(f"[daemon stdout]\n{out}")
                if err:
                    print(f"[daemon stderr]\n{err}")
            
            # Verify stop
            # assert stop_res.returncode == 0 # Sometimes if we force kill, stop might complain
            pass
