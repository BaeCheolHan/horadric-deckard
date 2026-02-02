import sys
import json
import socket
import threading
import os
import time
import subprocess
import logging
import fcntl
import sys
from pathlib import Path

# Add project root to sys.path for absolute imports
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.telemetry import TelemetryLogger
from app.workspace import WorkspaceManager

# Configure logging to stderr so it doesn't interfere with MCP STDIO
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("mcp-proxy")
telemetry = TelemetryLogger(WorkspaceManager.get_global_log_dir())


def _log_info(message: str) -> None:
    logger.info(message)
    try:
        telemetry.log_info(message)
    except Exception:
        pass


def _log_error(message: str) -> None:
    logger.error(message)
    try:
        telemetry.log_error(message)
    except Exception:
        pass

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

            _log_info("Daemon not running, starting...")
            
            # Assume we are in mcp/proxy.py, so parent of parent is repo root
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            def _detect_workspace_root_from_cwd():
                cwd = Path.cwd()
                for parent in [cwd] + list(cwd.parents):
                    if (parent / ".codex-root").exists():
                        return str(parent)
                return None

            env = os.environ.copy()
            if not env.get("DECKARD_WORKSPACE_ROOT") and not env.get("LOCAL_SEARCH_WORKSPACE_ROOT"):
                detected = _detect_workspace_root_from_cwd()
                if detected:
                    env["DECKARD_WORKSPACE_ROOT"] = detected
                    _log_info(f"Using workspace root from cwd marker: {detected}")
            
            # Detach process
            subprocess.Popen(
                [sys.executable, "-m", "mcp.daemon"],
                cwd=repo_root,
                env=env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for it to come up
            for _ in range(20):
                try:
                    with socket.create_connection((host, port), timeout=0.1):
                        _log_info("Daemon started successfully.")
                        return True
                except (ConnectionRefusedError, OSError):
                    time.sleep(0.1)
            
            _log_error("Failed to start daemon.")
            return False
            
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)

def forward_socket_to_stdout(sock, mode_holder):
    try:
        f = sock.makefile("rb")
        while True:
            # Read Headers
            headers = {}
            while True:
                line = f.readline()
                if not line:
                    break
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    break
                if ":" in line_str:
                    k, v = line_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            
            if not headers and not line:
                break
            
            content_length = int(headers.get("content-length", 0))
            if content_length <= 0:
                continue
                
            body = f.read(content_length)
            if not body:
                break
                
            mode = mode_holder.get("mode") or _MODE_FRAMED
            if mode == _MODE_JSONL:
                sys.stdout.buffer.write(body + b"\n")
                sys.stdout.buffer.flush()
            else:
                header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                sys.stdout.buffer.write(header + body)
                sys.stdout.buffer.flush()
    except Exception as e:
        _log_error(f"Error forwarding socket to stdout: {e}")
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
            # Inject rootUri for initialize when client omits it (per-connection workspace)
            try:
                req = json.loads(msg.decode("utf-8"))

                def _inject(obj):
                    if not isinstance(obj, dict) or obj.get("method") != "initialize":
                        return obj, False
                    params = obj.get("params") or {}
                    if params.get("rootUri") or params.get("rootPath"):
                        return obj, False
                    ws = os.environ.get("DECKARD_WORKSPACE_ROOT") or os.environ.get("LOCAL_SEARCH_WORKSPACE_ROOT")
                    if not ws:
                        return obj, False
                    params = dict(params)
                    params["rootUri"] = f"file://{ws}"
                    obj = dict(obj)
                    obj["params"] = params
                    _log_info(f"Injected rootUri for initialize: {ws}")
                    return obj, True

                injected = False
                if isinstance(req, dict):
                    req, injected = _inject(req)
                elif isinstance(req, list):
                    new_list = []
                    for item in req:
                        item2, did = _inject(item)
                        injected = injected or did
                        new_list.append(item2)
                    req = new_list

                if injected:
                    msg = json.dumps(req).encode("utf-8")
            except Exception:
                pass
            if mode_holder.get("mode") is None:
                mode_holder["mode"] = mode
            
            header = f"Content-Length: {len(msg)}\r\n\r\n".encode("ascii")
            sock.sendall(header + msg)
    except Exception as e:
        _log_error(f"Error forwarding stdin to socket: {e}")
        sock.close()
        sys.exit(1)

def main():
    # Log startup context for diagnostics
    _log_info(
        "Proxy startup: cwd=%s argv=%s env.DECKARD_WORKSPACE_ROOT=%s env.LOCAL_SEARCH_WORKSPACE_ROOT=%s"
        % (
            os.getcwd(),
            sys.argv,
            os.environ.get("DECKARD_WORKSPACE_ROOT"),
            os.environ.get("LOCAL_SEARCH_WORKSPACE_ROOT"),
        )
    )
    host = os.environ.get("DECKARD_DAEMON_HOST", DEFAULT_HOST)
    port = int(os.environ.get("DECKARD_DAEMON_PORT", DEFAULT_PORT))

    if not start_daemon_if_needed(host, port):
        sys.exit(1)

    try:
        sock = socket.create_connection((host, port))
    except Exception as e:
        _log_error(f"Could not connect to daemon: {e}")
        sys.exit(1)

    # Start threads for bidirectional forwarding
    mode_holder = {"mode": None}
    t1 = threading.Thread(target=forward_socket_to_stdout, args=(sock, mode_holder), daemon=True)
    t1.start()

    forward_stdin_to_socket(sock, mode_holder)

if __name__ == "__main__":
    main()
