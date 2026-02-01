import sys
import socket
import threading
import os
import time
import subprocess
import logging
import fcntl

# Configure logging to stderr so it doesn't interfere with MCP STDIO
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("mcp-proxy")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47779
_HEADER_SEP = b"\r\n\r\n"
_MODE_FRAMED = "framed"
_MODE_JSONL = "jsonl"

def start_daemon_if_needed(host, port):
    """Checks if daemon is running, if not starts it."""
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except (ConnectionRefusedError, OSError):
        pass

    lock_path = f"/tmp/deckard-daemon-{host}-{port}.lock"
    with open(lock_path, "w") as lock_file:
        try:
            # Acquire exclusive lock (blocking)
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            
            # Double-check if daemon started while waiting for lock
            try:
                with socket.create_connection((host, port), timeout=0.1):
                    return True
            except (ConnectionRefusedError, OSError):
                pass

            logger.info("Daemon not running, starting...")
            
            # Assume we are in mcp/proxy.py, so parent of parent is repo root
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # Detach process
            subprocess.Popen(
                [sys.executable, "-m", "mcp.daemon"],
                cwd=repo_root,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for it to come up
            for _ in range(20):
                try:
                    with socket.create_connection((host, port), timeout=0.1):
                        logger.info("Daemon started successfully.")
                        return True
                except (ConnectionRefusedError, OSError):
                    time.sleep(0.1)
            
            logger.error("Failed to start daemon.")
            return False
            
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)

def forward_socket_to_stdout(sock, mode_holder):
    try:
        f = sock.makefile("rb")
        while True:
            line = f.readline()
            if not line:
                break
            body = line.rstrip(b"\r\n")
            if not body:
                continue
            mode = mode_holder.get("mode") or _MODE_FRAMED
            if mode == _MODE_JSONL:
                sys.stdout.buffer.write(body + b"\n")
                sys.stdout.buffer.flush()
            else:
                header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                sys.stdout.buffer.write(header + body)
                sys.stdout.buffer.flush()
    except Exception as e:
        logger.error(f"Error forwarding socket to stdout: {e}")
    finally:
        # If socket closes, we should probably exit
        os._exit(0)

def _read_mcp_message(stdin):
    """Read one MCP framed message (Content-Length) or JSONL fallback."""
    line = stdin.readline()
    if not line:
        return None
    while line in (b"\n", b"\r\n"):
        line = stdin.readline()
        if not line:
            return None

    if line.lstrip().startswith((b"{", b"[")):
        return line.rstrip(b"\r\n"), _MODE_JSONL

    headers = [line]
    while True:
        h = stdin.readline()
        if not h:
            return None
        if h in (b"\n", b"\r\n"):
            break
        headers.append(h)

    content_length = None
    for h in headers:
        parts = h.decode("utf-8", errors="ignore").split(":", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip().lower()
        if key == "content-length":
            try:
                content_length = int(parts[1].strip())
            except ValueError:
                pass
            break

    if content_length is None:
        return None

    body = stdin.read(content_length)
    if not body:
        return None
    return body, _MODE_FRAMED


def forward_stdin_to_socket(sock, mode_holder):
    try:
        stdin = sys.stdin.buffer
        while True:
            res = _read_mcp_message(stdin)
            if res is None:
                break
            msg, mode = res
            if mode_holder.get("mode") is None:
                mode_holder["mode"] = mode
            sock.sendall(msg + b"\n")
    except Exception as e:
        logger.error(f"Error forwarding stdin to socket: {e}")
        sock.close()
        sys.exit(1)

def main():
    host = os.environ.get("DECKARD_DAEMON_HOST", DEFAULT_HOST)
    port = int(os.environ.get("DECKARD_DAEMON_PORT", DEFAULT_PORT))

    if not start_daemon_if_needed(host, port):
        sys.exit(1)

    try:
        sock = socket.create_connection((host, port))
    except Exception as e:
        logger.error(f"Could not connect to daemon: {e}")
        sys.exit(1)

    # Start threads for bidirectional forwarding
    mode_holder = {"mode": None}
    t1 = threading.Thread(target=forward_socket_to_stdout, args=(sock, mode_holder), daemon=True)
    t1.start()

    forward_stdin_to_socket(sock, mode_holder)

if __name__ == "__main__":
    main()
