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

def forward_socket_to_stdout(sock):
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except Exception as e:
        logger.error(f"Error forwarding socket to stdout: {e}")
    finally:
        # If socket closes, we should probably exit
        os._exit(0)

def forward_stdin_to_socket(sock):
    try:
        while True:
            data = sys.stdin.buffer.read(4096)
            if not data:
                break
            sock.sendall(data)
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
    t1 = threading.Thread(target=forward_socket_to_stdout, args=(sock,), daemon=True)
    t1.start()

    forward_stdin_to_socket(sock)

if __name__ == "__main__":
    main()
