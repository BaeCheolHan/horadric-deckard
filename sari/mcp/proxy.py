import sys
import json
import socket
import threading
import os
import time
import subprocess
import logging
import sys
import tempfile
import secrets
from pathlib import Path

# Add project root to sys.path for absolute imports
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sari.mcp.telemetry import TelemetryLogger
from sari.core.workspace import WorkspaceManager
from sari.core.server_registry import ServerRegistry
from sari.core.daemon_resolver import resolve_daemon_address as _resolve_daemon_target

try:
    import fcntl  # type: ignore
except Exception:
    fcntl = None

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
MAX_MESSAGE_SIZE = 10 * 1024 * 1024 # 10MB
_HEADER_SEP = b"\r\n\r\n"
_MODE_FRAMED = "framed"
_MODE_JSONL = "jsonl"


def _identify_sari_daemon(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "sari/identify"}).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            sock.sendall(header + body)

            f = sock.makefile("rb")
            headers = {}
            while True:
                line = f.readline()
                if not line:
                    return False
                line = line.strip()
                if not line:
                    break
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.strip().lower()] = v.strip()

            try:
                content_length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                return False
            if content_length <= 0:
                return False
            resp_body = f.read(content_length)
            if not resp_body:
                return False
            resp = json.loads(resp_body.decode("utf-8"))
            result = resp.get("result") or {}
            if result.get("name") == "sari":
                return True
    except Exception:
        pass
    return False


def _lock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return
    try:
        import msvcrt
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    except Exception:
        pass

def _unlock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        return
    try:
        import msvcrt
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass

def start_daemon_if_needed(host, port, workspace_root: str = ""):
    """Checks if daemon is running, if not starts it."""
    def _reap_child(proc: subprocess.Popen) -> None:
        try:
            proc.wait()
        except Exception:
            pass

    if _identify_sari_daemon(host, port):
        return True

    if not workspace_root:
        workspace_root = os.environ.get("SARI_WORKSPACE_ROOT") or WorkspaceManager.resolve_workspace_root()

    lock_path = os.path.join(tempfile.gettempdir(), f"sari-daemon-{host}-{port}.lock")
    with open(lock_path, "w") as lock_file:
        try:
            # Acquire exclusive lock (blocking)
            _lock_file(lock_file)

            # Double-check if daemon started while waiting for lock
            if _identify_sari_daemon(host, port):
                return True

            _log_info("Daemon not running, starting...")

            repo_root = Path(__file__).parent.parent.parent
            env = os.environ.copy()
            env["SARI_DAEMON_AUTOSTART"] = "1"
            env["SARI_WORKSPACE_ROOT"] = workspace_root

            proc = subprocess.Popen(
                [sys.executable, "-m", "sari.mcp.cli", "daemon", "start", "-d"],
                cwd=repo_root,
                env=env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Reap helper process when it exits to prevent defunct children in proxy.
            threading.Thread(target=_reap_child, args=(proc,), daemon=True).start()

            # Wait for it to come up (Increase to 10s for cold start reliability)
            for _ in range(100):
                host, port = _resolve_daemon_target()
                if _identify_sari_daemon(host, port):
                    _log_info("Daemon started successfully.")
                    return True
                time.sleep(0.1)

            _log_error("Failed to start daemon.")
            return False

        finally:
            _unlock_file(lock_file)

def forward_socket_to_stdout(sock, state):
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

            msg_id = None
            obj = None
            try:
                obj = json.loads(body.decode("utf-8"))
                if isinstance(obj, dict):
                    msg_id = obj.get("id")
            except Exception:
                msg_id = None
                obj = None

            # If daemon is draining, reconnect and replay initialize without
            # surfacing an error to the client.
            try:
                if isinstance(obj, dict):
                    err = obj.get("error") or {}
                    code = err.get("code")
                    message = str(err.get("message") or "")
                    if code == -32001 and "draining" in message.lower():
                        _log_info("Server draining detected; reconnecting to latest daemon.")
                        state["dead"] = True
                        if _reconnect(state):
                            init_req = state.get("init_request")
                            if init_req:
                                _send_payload(
                                    state,
                                    json.dumps(init_req).encode("utf-8"),
                                    state.get("mode") or _MODE_FRAMED,
                                )
                            continue
            except Exception:
                pass
            if msg_id is not None:
                with state["suppress_lock"]:
                    suppress_ids = state.setdefault("suppress_ids", set())
                    if msg_id in suppress_ids:
                        suppress_ids.discard(msg_id)
                        continue

            mode = state.get("mode") or _MODE_FRAMED
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
        state["dead"] = True
        try:
            sock.close()
        except Exception:
            pass

def _read_mcp_message(stdin):
    """Read one MCP framed message (Content-Length) or JSONL fallback."""
    line = stdin.readline()
    if not line:
        return None
    while line in (b"\n", b"\r\n"):
        line = stdin.readline()
        if not line:
            return None

    # Compatibility mode: accept JSONL fallback as well as Content-Length framing.
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

    if content_length is None or content_length <= 0 or content_length > MAX_MESSAGE_SIZE:
        return None

    body = b""
    while len(body) < content_length:
        chunk = stdin.read(content_length - len(body))
        if not chunk:
            break
        body += chunk

    if len(body) < content_length:
        return None
    return body, _MODE_FRAMED


def _send_payload(state, payload: bytes, mode: str) -> None:
    sock = state.get("sock")
    if not sock:
        raise OSError("socket not connected")
    if mode == _MODE_JSONL:
        sock.sendall(payload + b"\n")
    else:
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        sock.sendall(header + payload)


def _reconnect(state) -> bool:
    max_attempts = int(os.environ.get("SARI_PROXY_RECONNECT_MAX", "10") or 10)
    backoff = float(os.environ.get("SARI_PROXY_RECONNECT_BACKOFF", "0.2") or 0.2)
    with state["conn_lock"]:
        if not state.get("dead") and state.get("sock"):
            return True

        workspace_root = state.get("workspace_root") or ""
        last_err = None
        for _ in range(max_attempts):
            host, port = _resolve_daemon_target()
            if not start_daemon_if_needed(host, port, workspace_root=workspace_root):
                last_err = "daemon start failed"
                time.sleep(backoff)
                continue
            host, port = _resolve_daemon_target()
            try:
                sock = socket.create_connection((host, port))
                last_err = None
                break
            except Exception as e:
                last_err = str(e)
                time.sleep(backoff)
        else:
            _log_error(f"Reconnect failed: {last_err}")
            return False

        state["sock"] = sock
        state["dead"] = False

        t = threading.Thread(target=forward_socket_to_stdout, args=(sock, state), daemon=True)
        t.start()

        init_req = state.get("init_request")
        if init_req:
            try:
                internal = dict(init_req)
                with state["suppress_lock"]:
                    suppress_ids = state.setdefault("suppress_ids", set())
                    internal_id = -secrets.randbelow(2**31 - 1) - 1
                    while internal_id in suppress_ids:
                        internal_id = -secrets.randbelow(2**31 - 1) - 1
                    suppress_ids.add(internal_id)
                internal["id"] = internal_id
                _send_payload(state, json.dumps(internal).encode("utf-8"), state.get("mode") or _MODE_FRAMED)
            except Exception as e:
                _log_error(f"Reconnect initialize failed: {e}")
        return True


def forward_stdin_to_socket(state):
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
                        state["init_request"] = obj
                        return obj, False

                    # PRIORITY: SARI_
                    ws = None
                    val = os.environ.get("SARI_WORKSPACE_ROOT")
                    if val:
                        ws = val
                    
                    if not ws:
                        state["init_request"] = obj
                        return obj, False
                    params = dict(params)
                    params["rootUri"] = f"file://{ws}"
                    obj = dict(obj)
                    obj["params"] = params
                    _log_info(f"Injected rootUri for initialize: {ws}")
                    state["init_request"] = obj
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
            if state.get("mode") is None:
                state["mode"] = mode

            if state.get("dead"):
                if not _reconnect(state):
                    return
            try:
                with state["send_lock"]:
                    _send_payload(state, msg, mode)
            except Exception:
                state["dead"] = True
                if not _reconnect(state):
                    return
                with state["send_lock"]:
                    _send_payload(state, msg, mode)
    except Exception as e:
        _log_error(f"Error forwarding stdin to socket: {e}")
        try:
            sock = state.get("sock")
            if sock:
                sock.close()
        except Exception:
            pass

def main():
    # Log startup context for diagnostics
    _log_info(
        "Proxy startup: cwd=%s argv=%s SARI_ROOT=%s"
        % (
            os.getcwd(),
            sys.argv,
            os.environ.get("SARI_WORKSPACE_ROOT"),
        )
    )

    workspace_root = os.environ.get("SARI_WORKSPACE_ROOT") or WorkspaceManager.resolve_workspace_root()
    host, port = _resolve_daemon_target()

    if not start_daemon_if_needed(host, port, workspace_root=workspace_root):
        sys.exit(1)

    try:
        host, port = _resolve_daemon_target()
        sock = socket.create_connection((host, port))
    except Exception as e:
        _log_error(f"Could not connect to daemon: {e}")
        sys.exit(1)

    # Start threads for bidirectional forwarding
    state = {
        "mode": None,
        "sock": sock,
        "dead": False,
        "send_lock": threading.Lock(),
        "conn_lock": threading.Lock(),
        "suppress_lock": threading.Lock(),
        "suppress_ids": set(),
        "init_request": None,
        "workspace_root": workspace_root,
    }
    t1 = threading.Thread(target=forward_socket_to_stdout, args=(sock, state), daemon=True)
    t1.start()

    forward_stdin_to_socket(state)
    t1.join(timeout=1.0)

if __name__ == "__main__":
    main()
