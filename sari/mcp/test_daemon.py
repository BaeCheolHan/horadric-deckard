import asyncio
import json
import socket
import subprocess
import sys
import time
import os
import signal
from pathlib import Path

DAEMON_PORT = 47780
DAEMON_HOST = "127.0.0.1"

def wait_for_port(port, timeout=5):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((DAEMON_HOST, port), timeout=0.1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False

def send_rpc(sock, method, params=None, msg_id=1):
    req = {
        "jsonrpc": "2.0",
        "method": method,
        "id": msg_id,
        "params": params or {}
    }
    body = json.dumps(req).encode('utf-8')
    header = f"Content-Length: {len(body)}\r\n\r\n".encode('ascii')
    sock.sendall(header + body)

    # Read response
    f = sock.makefile('rb')
    # Read headers
    headers = {}
    while True:
        line = f.readline()
        if not line or line == b"\r\n":
            break
        line_str = line.decode('utf-8').strip()
        if ":" in line_str:
            k, v = line_str.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    content_length = int(headers.get("content-length", 0))
    if content_length > 0:
        return json.loads(f.read(content_length).decode('utf-8'))
    return None

def test_daemon():
    print("Starting daemon...")
    env = os.environ.copy()
    env["SARI_DAEMON_PORT"] = str(DAEMON_PORT)

    # Run as module from repo root
    repo_root = Path(__file__).parent.parent

    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp.daemon"],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        if not wait_for_port(DAEMON_PORT):
            print("Daemon failed to start")
            print(proc.stderr.read())
            sys.exit(1)

        print("Daemon started.")

        # Client 1: WS1
        s1 = socket.create_connection((DAEMON_HOST, DAEMON_PORT))
        print("Client 1 connected")
        res1 = send_rpc(s1, "initialize", {"rootUri": "file:///tmp/test_ws1"})
        print(f"Client 1 init result: {res1}")
        assert "result" in res1

        # Client 2: WS1 (Should share indexer)
        s2 = socket.create_connection((DAEMON_HOST, DAEMON_PORT))
        print("Client 2 connected")
        res2 = send_rpc(s2, "initialize", {"rootUri": "file:///tmp/test_ws1"})
        print(f"Client 2 init result: {res2}")
        assert "result" in res2

        # Client 3: WS2 (New indexer)
        s3 = socket.create_connection((DAEMON_HOST, DAEMON_PORT))
        print("Client 3 connected")
        res3 = send_rpc(s3, "initialize", {"rootUri": "file:///tmp/test_ws2"})
        print(f"Client 3 init result: {res3}")
        assert "result" in res3

        # Verify functionality - e.g. tools/list
        res_list = send_rpc(s1, "tools/list", {}, msg_id=2)
        assert len(res_list["result"]["tools"]) > 0
        print("Client 1 tools list OK")

        # Clean up
        s1.close()
        s2.close()
        s3.close()
        print("Clients disconnected")

        time.sleep(1) # Allow daemon to log disconnects

    finally:
        print("Stopping daemon...")
        proc.terminate()
        try:
            outs, errs = proc.communicate(timeout=2)
            print("Daemon stdout:", outs)
            print("Daemon stderr:", errs)
        except subprocess.TimeoutExpired:
            proc.kill()
            print("Daemon killed")

if __name__ == "__main__":
    test_daemon()