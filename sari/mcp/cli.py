#!/usr/bin/env python3
"""
Sari CLI - Command-line interface for daemon management.

Usage:
    sari daemon start [-d]   Start daemon (foreground or daemonized)
    sari daemon stop         Stop running daemon
    sari daemon status       Check daemon status
    sari proxy               Run in proxy mode (stdio ↔ daemon)
"""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import ipaddress
try:
    import psutil
except ImportError:
    psutil = None
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Add project root to sys.path for absolute imports
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from sari.core.workspace import WorkspaceManager
from sari.core.server_registry import ServerRegistry, REGISTRY_FILE
from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.core.daemon_resolver import resolve_daemon_address as get_daemon_address
from sari.mcp.tools.grep_and_read import execute_grep_and_read
from sari.mcp.tools.save_snippet import build_save_snippet
from sari.mcp.tools.get_snippet import build_get_snippet
from sari.mcp.tools.archive_context import build_archive_context
from sari.mcp.tools.get_context import build_get_context
from sari.mcp.tools.dry_run_diff import build_dry_run_diff


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47779
PID_FILE = WorkspaceManager.get_global_data_dir() / "daemon.pid"
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 47777


def _package_config_path() -> Path:
    return Path(__file__).parent.parent / "config" / "config.json"


def _load_config(workspace_root: str) -> Config:
    cfg_path = WorkspaceManager.resolve_config_path(workspace_root)
    return Config.load(cfg_path, workspace_root_override=workspace_root)


def _load_local_db(workspace_root: Optional[str] = None):
    root = workspace_root or WorkspaceManager.resolve_workspace_root()
    cfg_path = WorkspaceManager.resolve_config_path(root)
    cfg = Config.load(cfg_path, workspace_root_override=root)
    db = LocalSearchDB(cfg.db_path)
    return db, cfg.workspace_roots, root

def _load_server_info(workspace_root: str) -> Optional[dict]:
    """Legacy server.json location for backward compatibility."""
    server_json = Path(workspace_root) / ".codex" / "tools" / "sari" / "data" / "server.json"
    if not server_json.exists():
        return None
    try:
        return json.loads(server_json.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_registry_instances() -> Dict[str, Any]:
    try:
        if REGISTRY_FILE.exists():
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8")).get("instances", {})
    except Exception:
        pass
    return {}


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _enforce_loopback(host: str) -> None:
    # Security: Always enforce loopback. No overrides allowed.
    if not _is_loopback(host):
        raise RuntimeError(
            f"sari loopback-only: server_host must be 127.0.0.1/localhost/::1 (got={host}). "
            "Remote access is NOT supported for security."
        )


def _get_http_host_port(host_override: Optional[str] = None, port_override: Optional[int] = None) -> tuple[str, int]:
    """Get active HTTP server address with explicit/env/server/registry/config priority."""
    env_host = os.environ.get("SARI_HTTP_API_HOST") or os.environ.get("SARI_HTTP_HOST")
    env_port = os.environ.get("SARI_HTTP_API_PORT") or os.environ.get("SARI_HTTP_PORT")
    workspace_root = WorkspaceManager.resolve_workspace_root()
    cfg = _load_config(str(workspace_root))

    host = cfg.http_api_host or DEFAULT_HTTP_HOST
    port = int(cfg.http_api_port or DEFAULT_HTTP_PORT)

    try:
        ws_info = ServerRegistry().get_workspace(str(workspace_root))
        if ws_info:
            if ws_info.get("http_host"):
                host = str(ws_info.get("http_host"))
            if ws_info.get("http_port"):
                port = int(ws_info.get("http_port"))
    except Exception:
        pass

    server_info = _load_server_info(str(workspace_root))
    if server_info:
        try:
            if server_info.get("host"):
                host = str(server_info.get("host"))
            if server_info.get("port"):
                port = int(server_info.get("port"))
        except Exception:
            pass

    if env_host:
        host = env_host
    if env_port:
        try:
            port = int(env_port)
        except (TypeError, ValueError):
            pass

    if host_override:
        host = host_override
    if port_override is not None:
        port = int(port_override)

    return host, port



def _request_http(path: str, params: dict, host: Optional[str] = None, port: Optional[int] = None) -> dict:
    host, port = _get_http_host_port(host, port)
    _enforce_loopback(host)
    qs = urllib.parse.urlencode(params)
    url = f"http://{host}:{port}{path}?{qs}"
    with urllib.request.urlopen(url, timeout=3.0) as r:
        return json.loads(r.read().decode("utf-8"))


def _is_http_running(host: str, port: int, timeout: float = 0.4) -> bool:
    _enforce_loopback(host)
    try:
        url = f"http://{host}:{port}/health"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status != 200:
                return False
            payload = json.loads(r.read().decode("utf-8"))
            return bool(payload.get("ok"))
    except Exception:
        return False


def _identify_sari_daemon(host: str, port: int, timeout: float = 0.3) -> Optional[Dict[str, Any]]:
    """Return identify payload if the server speaks Sari MCP."""
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
                    return None
                line = line.strip()
                if not line:
                    break
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.strip().lower()] = v.strip()

            try:
                content_length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                return None
            if content_length <= 0:
                return None
            resp_body = f.read(content_length)
            if not resp_body:
                return None
            resp = json.loads(resp_body.decode("utf-8"))

            result = resp.get("result") or {}
            if result.get("name") == "sari":
                return result
    except Exception:
        pass

    # Legacy fallback: probe "ping" and accept "Server not initialized" error
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            sock.sendall(header + body)

            f = sock.makefile("rb")
            headers = {}
            while True:
                line = f.readline()
                if not line:
                    return None
                line = line.strip()
                if not line:
                    break
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.strip().lower()] = v.strip()

            try:
                content_length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                return None
            if content_length <= 0:
                return None
            resp_body = f.read(content_length)
            if not resp_body:
                return None
            resp = json.loads(resp_body.decode("utf-8"))
            err = resp.get("error") or {}
            msg = (err.get("message") or "").lower()
            if "server not initialized" in msg:
                return {"name": "sari", "version": "legacy", "protocolVersion": ""}
    except Exception:
        pass

    return None


def _ensure_workspace_http(daemon_host: str, daemon_port: int, workspace_root: Optional[str] = None) -> bool:
    """Ensure workspace is initialized so HTTP server is started/registered."""
    try:
        root = workspace_root or os.environ.get("SARI_WORKSPACE_ROOT") or WorkspaceManager.resolve_workspace_root()
        with socket.create_connection((daemon_host, daemon_port), timeout=1.0) as sock:
            body = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"rootUri": f"file://{root}", "capabilities": {}},
            }).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            sock.sendall(header + body)
            f = sock.makefile("rb")
            headers = {}
            while True:
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    break
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.strip().lower()] = v.strip()
            try:
                content_length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                content_length = 0
            if content_length > 0:
                f.read(content_length)
        return True
    except Exception:
        return False


def _request_mcp_status(daemon_host: str, daemon_port: int, workspace_root: Optional[str] = None) -> Optional[dict]:
    try:
        root = workspace_root or os.environ.get("SARI_WORKSPACE_ROOT") or WorkspaceManager.resolve_workspace_root()
        with socket.create_connection((daemon_host, daemon_port), timeout=2.0) as sock:
            def _send(payload: dict) -> dict:
                body = json.dumps(payload).encode("utf-8")
                header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                sock.sendall(header + body)
                f = sock.makefile("rb")
                headers = {}
                while True:
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        break
                    if b":" in line:
                        k, v = line.split(b":", 1)
                        headers[k.strip().lower()] = v.strip()
                try:
                    content_length = int(headers.get(b"content-length", b"0"))
                except ValueError:
                    content_length = 0
                body = f.read(content_length) if content_length > 0 else b""
                return json.loads(body.decode("utf-8")) if body else {}

            _send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"rootUri": f"file://{root}", "capabilities": {}},
            })
            resp = _send({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "status", "arguments": {"details": True}},
            })
            return resp.get("result") or resp
    except Exception:
        return None


def _probe_sari_daemon(host: str, port: int, timeout: float = 0.3) -> bool:
    """Verify the server speaks Sari MCP (framed JSON-RPC)."""
    return _identify_sari_daemon(host, port, timeout=timeout) is not None


def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return False
    except OSError:
        return True


def is_daemon_running(host: str, port: int) -> bool:
    """Check if a Sari daemon is running on the given port."""
    return _probe_sari_daemon(host, port)


def read_pid() -> Optional[int]:
    """Read PID from pidfile."""
    try:
        workspace_root = os.environ.get("SARI_WORKSPACE_ROOT") or WorkspaceManager.resolve_workspace_root()
        inst = ServerRegistry().resolve_workspace_daemon(str(workspace_root))
        if inst and inst.get("pid"):
            return int(inst.get("pid"))
    except Exception:
        pass
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return None


def remove_pid() -> None:
    """Remove pidfile manually (if daemon crashed)."""
    if PID_FILE.exists():
        PID_FILE.unlink()


def _get_local_version() -> str:
    try:
        from sari.version import __version__ as v
        return v or ""
    except Exception:
        return os.environ.get("SARI_VERSION", "") or ""


def _build_start_args(
    daemonize: bool = True,
    daemon_host: str = "",
    daemon_port: Optional[int] = None,
    http_host: str = "",
    http_port: Optional[int] = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        daemonize=daemonize,
        daemon_host=daemon_host,
        daemon_port=daemon_port,
        http_host=http_host,
        http_port=http_port,
    )


def _start_daemon_background(
    daemon_host: str = "",
    daemon_port: Optional[int] = None,
    http_host: str = "",
    http_port: Optional[int] = None,
) -> bool:
    start_args = _build_start_args(
        daemonize=True,
        daemon_host=daemon_host,
        daemon_port=daemon_port,
        http_host=http_host,
        http_port=http_port,
    )
    return cmd_daemon_start(start_args) == 0


def _needs_upgrade_or_drain(identify: Optional[Dict[str, Any]]) -> bool:
    if not identify:
        return False
    existing_version = identify.get("version") or ""
    local_version = _get_local_version()
    draining = bool(identify.get("draining"))
    needs_upgrade = bool(existing_version and local_version and existing_version != local_version)
    return bool(needs_upgrade or draining)


def _ensure_daemon_running(
    daemon_host: str,
    daemon_port: int,
    http_host: str = "",
    http_port: Optional[int] = None,
    allow_upgrade: bool = False,
) -> Tuple[str, int, bool]:
    identify = _identify_sari_daemon(daemon_host, daemon_port)
    if identify and not (allow_upgrade and _needs_upgrade_or_drain(identify)):
        return daemon_host, daemon_port, True

    if allow_upgrade and identify and _needs_upgrade_or_drain(identify):
        _start_daemon_background(daemon_host, daemon_port, http_host, http_port)
        daemon_host, daemon_port = get_daemon_address()
        return daemon_host, daemon_port, is_daemon_running(daemon_host, daemon_port)

    if not is_daemon_running(daemon_host, daemon_port):
        _start_daemon_background(daemon_host, daemon_port, http_host, http_port)
        daemon_host, daemon_port = get_daemon_address()
        return daemon_host, daemon_port, is_daemon_running(daemon_host, daemon_port)

    return daemon_host, daemon_port, True


def cmd_daemon_start(args):
    """Start the daemon."""
    explicit_port = bool(args.daemon_port)
    force_start = (os.environ.get("SARI_DAEMON_FORCE_START") or "").strip().lower() in {"1", "true", "yes", "on"}
    workspace_root = os.environ.get("SARI_WORKSPACE_ROOT") or WorkspaceManager.resolve_workspace_root()
    registry = ServerRegistry()

    if args.daemon_host or args.daemon_port:
        host = args.daemon_host or DEFAULT_HOST
        port = int(args.daemon_port or DEFAULT_PORT)
    else:
        inst = registry.resolve_workspace_daemon(str(workspace_root))
        if inst and inst.get("port"):
            host = inst.get("host") or DEFAULT_HOST
            port = int(inst.get("port"))
        else:
            host = DEFAULT_HOST
            port = DEFAULT_PORT

    identify = _identify_sari_daemon(host, port)
    if identify:
        if not force_start and not _needs_upgrade_or_drain(identify):
            pid = read_pid()
            print(f"✅ Daemon already running on {host}:{port}")
            if not pid:
                print("⚠️  PID file missing. Another process may be using this port.")
                print("   Hint: Try a different port: SARI_DAEMON_PORT=47790 sari daemon start -d")
            return 0
        if explicit_port:
            print(f"❌ Port {port} is already in use by a running Sari daemon.", file=sys.stderr)
            return 1
        port = registry.find_free_port(start_port=47790)
        print(f"⚠️  Starting new daemon on free port {port} (upgrade/drain).")
    elif _port_in_use(host, port):
        if explicit_port:
            print(f"❌ Port {port} is already in use by another process.", file=sys.stderr)
            return 1
        # Choose a free port to avoid collisions with other MCP daemons.
        free_port = registry.find_free_port(start_port=47790)
        print(f"⚠️  Port {port} is in use. Switching to free port {free_port}.")
        port = free_port

    repo_root = Path(__file__).parent.parent.resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["SARI_DAEMON_AUTOSTART"] = "1"
    env["SARI_WORKSPACE_ROOT"] = workspace_root
    env["SARI_DAEMON_PORT"] = str(port)
    if args.daemon_host:
        env["SARI_DAEMON_HOST"] = args.daemon_host
    if args.daemon_port:
        env["SARI_DAEMON_PORT"] = str(args.daemon_port)
    if args.http_host:
        env["SARI_HTTP_API_HOST"] = args.http_host
    if args.http_port is not None:
        env["SARI_HTTP_API_PORT"] = str(args.http_port)

    if args.daemonize:
        # Start in background
        print(f"Starting daemon on {host}:{port} (background)...")

        proc = subprocess.Popen(
            [sys.executable, "-m", "sari.mcp.daemon"],
            cwd=repo_root.parent,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        # PID file will be written by the daemon process itself

        # Wait for startup
        for _ in range(30):
            if is_daemon_running(host, port):
                print(f"✅ Daemon started (PID: {proc.pid})")
                return 0
            time.sleep(0.1)

        print("❌ Daemon failed to start", file=sys.stderr)
        return 1
    else:
        # Start in foreground
        print(f"Starting daemon on {host}:{port} (foreground, Ctrl+C to stop)...")

        try:
            # Import and run directly
            os.environ["SARI_DAEMON_AUTOSTART"] = "1"
            os.environ["SARI_WORKSPACE_ROOT"] = workspace_root
            os.environ["PYTHONPATH"] = str(repo_root) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
            if args.daemon_host:
                os.environ["SARI_DAEMON_HOST"] = args.daemon_host
            if args.daemon_port:
                os.environ["SARI_DAEMON_PORT"] = str(args.daemon_port)
            if args.http_host:
                os.environ["SARI_HTTP_API_HOST"] = args.http_host
            if args.http_port is not None:
                os.environ["SARI_HTTP_API_PORT"] = str(args.http_port)
            from sari.mcp.daemon import main as daemon_main
            import asyncio
            asyncio.run(daemon_main())
        except KeyboardInterrupt:
            print("\nDaemon stopped.")

        return 0


def cmd_daemon_stop(args):
    """Stop the daemon."""
    host, port = get_daemon_address()

    if not is_daemon_running(host, port):
        print("Daemon is not running")
        remove_pid()
        return 0

    pid = read_pid()

    if pid:
        try:
            if os.name == 'nt':
                # Windows force kill
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
                print(f"Executed taskkill for PID {pid}")
            else:
                # Verify PID is actually sari/python before killing
                try:
                    if psutil:
                        proc = psutil.Process(pid)
                        proc_name = proc.name().lower()
                        cmdline = " ".join(proc.cmdline()).lower()
                        # Check if it looks like a python process running sari
                        if "python" in proc_name or "sari" in cmdline or "sari.mcp.daemon" in cmdline:
                            os.kill(pid, signal.SIGTERM)
                            print(f"Sent SIGTERM to PID {pid}")
                        else:
                            print(f"❌ Safety Check Failed: PID {pid} ({proc_name}) does not look like Sari. Aborting.")
                            print(f"   Cmdline: {cmdline}")
                            return 1
                    else:
                        # Fallback if psutil missing (warn but proceed? or strictly fail?)
                        # Plan said "Use psutil". If missing, we can't be safe.
                        # But failing completely prevents stopping.
                        print(f"⚠️  psutil not installed. Skipping safety check for PID {pid}.")
                        os.kill(pid, signal.SIGTERM)
                        print(f"Sent SIGTERM to PID {pid}")
                except Exception as e:
                    if psutil and isinstance(e, psutil.NoSuchProcess):
                        print(f"PID {pid} not found (already stopped?)")
                        remove_pid()
                        return 0
                    # Handle psutil error or undefined
                    # If psutil is None, we already handled in else block?
                    # Wait, if psutil is None, we go to else block.
                    # This except catches psutil.NoSuchProcess.
                    # If psutil is None, name 'psutil' exists but is None.
                    # isinstance(e, None) raises TypeError.
                    raise e

            # Wait for shutdown
            for _ in range(30):
                if not is_daemon_running(host, port):
                    print("✅ Daemon stopped")
                    remove_pid()
                    return 0
                time.sleep(0.1)

            # Force kill (Unix only, Windows already done with /F)
            if os.name != 'nt':
                print("Daemon not responding, sending SIGKILL...")
                os.kill(pid, signal.SIGKILL)

            remove_pid()
            return 0

        except (ProcessLookupError, PermissionError):
            print("PID not found or permission denied, daemon may have crashed or locked")
            remove_pid()
            return 0
    else:
        print("No PID file found. Try stopping manually.")
        return 1


def cmd_daemon_status(args):
    """Check daemon status."""
    host, port = get_daemon_address()

    running = is_daemon_running(host, port)
    pid = read_pid()

    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Status: {'🟢 Running' if running else '⚫ Stopped'}")

    if pid:
        print(f"PID: {pid}")

    if running:
        # Try to get workspace info
        try:
            with socket.create_connection((host, port), timeout=1.0) as sock:
                # Send a status request
                import json
                request = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "status", "arguments": {"details": True}}
                }) + "\n"
                sock.sendall(request.encode())

                # We'd need an initialize first, so just skip detailed status for now
        except Exception:
            pass

    return 0 if running else 1


def cmd_proxy(args):
    """Run in proxy mode (for MCP stdio)."""
    from sari.mcp.proxy import main as proxy_main
    proxy_main()


def _tcp_blocked(err: OSError) -> bool:
    return getattr(err, "errno", None) in (1, 13)


def cmd_auto(args):
    """Try TCP daemon/proxy first, fallback to STDIO server."""
    host, port = get_daemon_address()

    # Fast path: if TCP is blocked by sandbox, skip daemon/proxy.
    try:
        with socket.create_connection((host, port), timeout=0.1):
            pass
    except OSError as e:
        if _tcp_blocked(e):
            from sari.mcp.server import main as server_main
            server_main()
            return 0
        # Connection refused etc. We'll try to start daemon below.

    identify = _identify_sari_daemon(host, port)
    if identify and not _needs_upgrade_or_drain(identify):
        return cmd_proxy(args)
    if identify and _needs_upgrade_or_drain(identify):
        host, port, running = _ensure_daemon_running(host, port, allow_upgrade=True)
        if running:
            return cmd_proxy(args)

    # Try to start daemon in background, then proxy.
    if not is_daemon_running(host, port):
        _start_daemon_background()
        for _ in range(30):
            try:
                host, port = get_daemon_address()
                if is_daemon_running(host, port):
                    break
            except OSError as e:
                if _tcp_blocked(e):
                    from sari.mcp.server import main as server_main
                    server_main()
                    return 0
            time.sleep(0.1)

    if is_daemon_running(host, port):
        return cmd_proxy(args)

    # Final fallback to STDIO server.
    from sari.mcp.server import main as server_main
    server_main()
    return 0


def cmd_status(args):
    """Query HTTP status endpoint."""
    try:
        if args.daemon_host or args.daemon_port:
            daemon_host = args.daemon_host or DEFAULT_HOST
            daemon_port = int(args.daemon_port or DEFAULT_PORT)
        else:
            daemon_host, daemon_port = get_daemon_address()
        daemon_running = is_daemon_running(daemon_host, daemon_port)
        host, port = _get_http_host_port(args.http_host, args.http_port)
        http_running = _is_http_running(host, port)

        if not http_running:
            if not daemon_running:
                daemon_host, daemon_port, daemon_running = _ensure_daemon_running(
                    daemon_host,
                    daemon_port,
                    http_host=args.http_host,
                    http_port=args.http_port,
                    allow_upgrade=False,
                )
            if daemon_running:
                for _ in range(5):
                    _ensure_workspace_http(daemon_host, daemon_port)
                    host, port = _get_http_host_port(args.http_host, args.http_port)
                    http_running = _is_http_running(host, port)
                    if http_running:
                        break
                    time.sleep(0.1)
            if not http_running and daemon_running:
                fallback = _request_mcp_status(daemon_host, daemon_port)
                if fallback:
                    print(json.dumps(fallback, ensure_ascii=False, indent=2))
                    return 0
            print("❌ Error: Sari services are not fully running.")
            print(f"   Daemon: {'🟢' if daemon_running else '⚫'} {daemon_host}:{daemon_port}")
            print(f"   HTTP:   {'🟢' if http_running else '⚫'} {host}:{port}")
            try:
                ws_root = WorkspaceManager.resolve_workspace_root()
                server_info = _load_server_info(str(ws_root))
                if server_info and server_info.get("port") and int(server_info.get("port")) != int(port):
                    note_host = server_info.get("host") or host
                    note_port = server_info.get("port")
                    print(f"   Note: server.json reports {note_host}:{note_port}")
            except Exception:
                pass
            print("   Hint: Run `sari daemon start -d` to start both, or `sari --http-api` to start HTTP only.")
            return 1

        data = _request_http("/status", {}, host, port)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(f"❌ Error: Could not connect to Sari HTTP server.")
        print(f"   Details: {e}")
        print(f"   Hint: Make sure the Deamon is running for this workspace.")
        return 1


def cmd_search(args):
    """Query HTTP search endpoint."""
    params = {"q": args.query, "limit": args.limit}
    if args.repo:
        params["repo"] = args.repo
    data = _request_http("/search", params)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args):
    from sari.mcp.tools.doctor import execute_doctor
    include_network = True
    include_db = True
    include_port = True
    include_disk = True
    if args.no_network:
        include_network = False
    if args.no_db:
        include_db = False
    if args.no_port:
        include_port = False
    if args.no_disk:
        include_disk = False
    if args.include_network:
        include_network = True
    if args.include_db:
        include_db = True
    if args.include_port:
        include_port = True
    if args.include_disk:
        include_disk = True

    payload = execute_doctor(
        {
            "auto_fix": bool(args.auto_fix),
            "auto_fix_rescan": bool(args.auto_fix_rescan),
            "include_network": include_network,
            "include_db": include_db,
            "include_port": include_port,
            "include_disk": include_disk,
            "min_disk_gb": float(args.min_disk_gb),
        }
    )
    text = payload.get("content", [{}])[0].get("text", "")
    try:
        parsed = json.loads(text)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except Exception:
        print(text)
    return 0


def cmd_init(args):
    """Initialize workspace with Sari config."""
    workspace_root = Path(args.workspace).expanduser().resolve() if args.workspace else Path(WorkspaceManager.resolve_workspace_root()).resolve()
    cfg_path = Path(WorkspaceManager.resolve_config_path(str(workspace_root)))
    data_dir = workspace_root / ".codex" / "tools" / "sari" / "data"

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    from sari.core.config import Config
    default_cfg = Config.get_defaults(str(workspace_root))

    data = {}
    if cfg_path.exists() and not args.force:
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

    roots = data.get("roots") or data.get("workspace_roots") or []
    if not isinstance(roots, list):
        roots = []
    if str(workspace_root) not in roots:
        roots.append(str(workspace_root))
    data["roots"] = roots
    data.setdefault("db_path", default_cfg["db_path"])
    data.setdefault("exclude_dirs", default_cfg["exclude_dirs"])

    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"✅ Updated Sari config: {cfg_path}")
    print(f"\n🚀 Workspace initialized successfully at {workspace_root}")
    return 0


def cmd_call_graph(args):
    db, roots, _ = _load_local_db(args.workspace)
    try:
        payload = build_call_graph(
            {
                "symbol": args.symbol,
                "symbol_id": args.symbol_id or "",
                "path": args.path or "",
                "depth": args.depth,
                "include_path": args.include_path or [],
                "exclude_path": args.exclude_path or [],
                "sort": args.sort,
            },
            db,
            roots,
        )
        if args.format == "tree":
            print(payload.get("tree", ""))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_save_snippet(args):
    db, roots, _ = _load_local_db(args.workspace)
    try:
        payload = build_save_snippet(
            {
                "path": args.path,
                "start_line": args.start_line,
                "end_line": args.end_line,
                "tag": args.tag,
                "note": args.note or "",
                "commit": args.commit or "",
            },
            db,
            roots,
            indexer=None,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_get_snippet(args):
    db, roots, _ = _load_local_db(args.workspace)
    try:
        payload = build_get_snippet(
            {
                "tag": args.tag or "",
                "query": args.query or "",
                "limit": args.limit,
                "remap": (not args.no_remap),
                "history": args.history,
                "update": args.update,
                "diff_path": args.diff_path or "",
            },
            db,
            roots,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_archive_context(args):
    db, roots, _ = _load_local_db(args.workspace)
    try:
        payload = build_archive_context(
            {
                "topic": args.topic,
                "content": args.content,
                "tags": args.tags or [],
                "related_files": args.related_files or [],
                "source": args.source or "",
                "valid_from": args.valid_from or "",
                "valid_until": args.valid_until or "",
                "deprecated": args.deprecated,
            },
            db,
            indexer=None,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_get_context(args):
    db, roots, _ = _load_local_db(args.workspace)
    try:
        payload = build_get_context({"topic": args.topic or "", "query": args.query or "", "limit": args.limit, "as_of": args.as_of or ""}, db)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_dry_run_diff(args):
    db, roots, _ = _load_local_db(args.workspace)
    try:
        if args.lint:
            os.environ["SARI_DRYRUN_LINT"] = "1"
        payload = build_dry_run_diff({"path": args.path, "content": args.content}, db, roots)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()

def cmd_grep_and_read(args):
    db, roots, _ = _load_local_db(args.workspace)
    try:
        payload = execute_grep_and_read(
            {
                "query": args.query,
                "repo": args.repo or "",
                "limit": args.limit,
                "read_limit": args.read_limit,
                "file_types": args.file_types or [],
                "path_pattern": args.path_pattern or "",
                "exclude_patterns": args.exclude_patterns or [],
                "recency_boost": bool(args.recency_boost),
                "use_regex": bool(args.use_regex),
                "case_sensitive": bool(args.case_sensitive),
                "context_lines": args.context_lines,
                "total_mode": args.total_mode or "exact",
            },
            db,
            roots,
        )
        text = payload.get("content", [{}])[0].get("text", "")
        try:
            parsed = json.loads(text)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            print(text)
        return 0
    finally:
        db.close()



def cmd_prune(args):
    """Prune old data from auxiliary tables."""
    db, roots, _ = _load_local_db(args.workspace)
    try:
        tables = [args.table] if args.table else ["snippets", "failed_tasks", "contexts"]
        total_pruned = 0
        print(f"🧹 Pruning data older than {args.days or '(default)'} days...")
        
        for table in tables:
            ttl = args.days
            if ttl is None:
                # Fallback to settings
                if table == "snippets": ttl = db.settings.STORAGE_TTL_DAYS_SNIPPETS
                elif table == "failed_tasks": ttl = db.settings.STORAGE_TTL_DAYS_FAILED_TASKS
                elif table == "contexts": ttl = db.settings.STORAGE_TTL_DAYS_CONTEXTS
                else: ttl = 30 # Safe fallback
            
            count = db.prune_data(table, ttl)
            if count > 0:
                print(f"   - {table}: Removed {count} records (older than {ttl} days)")
                total_pruned += count
        
        if total_pruned == 0:
            print("✨ No data to prune.")
        else:
            print(f"✅ Total pruned: {total_pruned} records")
        return 0
    finally:
        db.close()


def main():

    epilog = "\n".join([
        "Examples:",
        "  sari daemon start -d",
        "  sari status",
        "  sari doctor --auto-fix",
        "  sari search \"query\" --limit 10",
        "  sari call-graph --symbol process_file --depth 2",
        "  sari save-snippet --path src/app.py --start-line 10 --end-line 20 --tag db-idiom",
        "  sari get-snippet --tag db-idiom",
        "  sari archive-context --topic PricingLogic --content \"...\"",
        "  sari get-context --query PricingLogic",
        "  sari dry-run-diff --path src/app.py --content \"<new content>\"",
        "  sari auto",
    ])
    parser = argparse.ArgumentParser(
        prog="sari",
        description="Sari - Local Search MCP Server",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=epilog,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # daemon subcommand
    daemon_parser = subparsers.add_parser("daemon", help="Daemon management")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_command")

    # daemon start
    start_parser = daemon_sub.add_parser("start", help="Start daemon")
    start_parser.add_argument("-d", "--daemonize", action="store_true",
                              help="Run in background")
    start_parser.add_argument("--daemon-host", default="", help="Daemon host override (default: 127.0.0.1)")
    start_parser.add_argument("--daemon-port", type=int, default=None, help="Daemon port override (default: 47779)")
    start_parser.add_argument("--http-host", default="", help="HTTP host override (default: 127.0.0.1)")
    start_parser.add_argument("--http-port", type=int, default=None, help="HTTP port override (default: 47777)")
    start_parser.set_defaults(func=cmd_daemon_start)

    # daemon stop
    stop_parser = daemon_sub.add_parser("stop", help="Stop daemon")
    stop_parser.set_defaults(func=cmd_daemon_stop)

    # daemon status
    status_parser = daemon_sub.add_parser("status", help="Check status")
    status_parser.set_defaults(func=cmd_daemon_status)

    # proxy subcommand
    proxy_parser = subparsers.add_parser("proxy", help="Run in proxy mode")
    proxy_parser.set_defaults(func=cmd_proxy)

    # auto subcommand
    auto_parser = subparsers.add_parser("auto", help="Auto mode (daemon/proxy fallback)")
    auto_parser.set_defaults(func=cmd_auto)

    # status subcommand (HTTP)
    status_parser = subparsers.add_parser("status", help="Query HTTP status")
    status_parser.add_argument("--daemon-host", default="", help="Daemon host override (default: 127.0.0.1)")
    status_parser.add_argument("--daemon-port", type=int, default=None, help="Daemon port override (default: 47779)")
    status_parser.add_argument("--http-host", default="", help="HTTP host override (default: 127.0.0.1)")
    status_parser.add_argument("--http-port", type=int, default=None, help="HTTP port override (default: 47777)")
    status_parser.set_defaults(func=cmd_status)

    # doctor subcommand
    doctor_parser = subparsers.add_parser("doctor", help="Run diagnostics")
    doctor_parser.add_argument("--auto-fix", action="store_true", help="Attempt automatic fixes when possible")
    doctor_parser.add_argument("--auto-fix-rescan", action="store_true", help="Run scan_once after auto-fix")
    doctor_parser.add_argument("--include-network", action="store_true", help="Include network check")
    doctor_parser.add_argument("--no-network", action="store_true", help="Skip network check")
    doctor_parser.add_argument("--include-db", action="store_true", help="Include DB check")
    doctor_parser.add_argument("--no-db", action="store_true", help="Skip DB check")
    doctor_parser.add_argument("--include-port", action="store_true", help="Include port check")
    doctor_parser.add_argument("--no-port", action="store_true", help="Skip port check")
    doctor_parser.add_argument("--include-disk", action="store_true", help="Include disk check")
    doctor_parser.add_argument("--no-disk", action="store_true", help="Skip disk check")
    doctor_parser.add_argument("--min-disk-gb", type=float, default=1.0, help="Minimum disk space GB")
    doctor_parser.set_defaults(func=cmd_doctor)

    # search subcommand (HTTP)
    search_parser = subparsers.add_parser("search", help="Search via HTTP server")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--repo", default="", help="Limit search to repo")
    search_parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    search_parser.set_defaults(func=cmd_search)

    # init subcommand
    init_parser = subparsers.add_parser("init", help="Initialize workspace config")
    init_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config")
    init_parser.set_defaults(func=cmd_init)

    # call-graph
    cg_parser = subparsers.add_parser("call-graph", help="Call graph for a symbol")
    cg_parser.add_argument("--symbol", required=True, help="Target symbol name")
    cg_parser.add_argument("--symbol-id", default="", help="Optional symbol_id to disambiguate")
    cg_parser.add_argument("--path", default="", help="Optional db-path or file path to disambiguate")
    cg_parser.add_argument("--depth", type=int, default=2, help="Graph depth (default: 2)")
    cg_parser.add_argument("--format", default="json", choices=["json", "tree"], help="Output format")
    cg_parser.add_argument("--include-path", nargs="*", default=[], help="Include paths (prefix or substring)")
    cg_parser.add_argument("--exclude-path", nargs="*", default=[], help="Exclude paths (prefix or substring)")
    cg_parser.add_argument("--sort", default="line", choices=["line", "name"], help="Tree sort order")
    cg_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    cg_parser.set_defaults(func=cmd_call_graph)

    # save-snippet
    ss_parser = subparsers.add_parser("save-snippet", help="Save code snippet")
    ss_parser.add_argument("--path", required=True, help="Path or path:start-end")
    ss_parser.add_argument("--start-line", type=int, default=None)
    ss_parser.add_argument("--end-line", type=int, default=None)
    ss_parser.add_argument("--tag", required=True, help="Tag for snippet")
    ss_parser.add_argument("--note", default="", help="Optional note")
    ss_parser.add_argument("--commit", default="", help="Optional commit hash")
    ss_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    ss_parser.set_defaults(func=cmd_save_snippet)

    # get-snippet
    gs_parser = subparsers.add_parser("get-snippet", help="Get saved snippet")
    gs_parser.add_argument("--tag", default="", help="Tag to lookup")
    gs_parser.add_argument("--query", default="", help="Search query")
    gs_parser.add_argument("--limit", type=int, default=20, help="Max results")
    gs_parser.add_argument("--no-remap", action="store_true", help="Disable remap against current file")
    gs_parser.add_argument("--history", action="store_true", help="Include snippet versions")
    gs_parser.add_argument("--update", action="store_true", help="Write back remapped location/content")
    gs_parser.add_argument("--diff-path", default="", help="Write remap diff to file when --update is used")
    gs_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    gs_parser.set_defaults(func=cmd_get_snippet)

    # archive-context
    ac_parser = subparsers.add_parser("archive-context", help="Archive domain context")
    ac_parser.add_argument("--topic", required=True, help="Context topic")
    ac_parser.add_argument("--content", required=True, help="Context content")
    ac_parser.add_argument("--tags", nargs="*", default=[], help="Tags")
    ac_parser.add_argument("--related-files", nargs="*", default=[], help="Related files")
    ac_parser.add_argument("--source", default="", help="Context source (doc/issue/link)")
    ac_parser.add_argument("--valid-from", default="", help="Valid from (timestamp or ISO date)")
    ac_parser.add_argument("--valid-until", default="", help="Valid until (timestamp or ISO date)")
    ac_parser.add_argument("--deprecated", action="store_true", help="Mark context as deprecated")
    ac_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    ac_parser.set_defaults(func=cmd_archive_context)

    # get-context
    gc_parser = subparsers.add_parser("get-context", help="Get archived context")
    gc_parser.add_argument("--topic", default="", help="Topic to lookup")
    gc_parser.add_argument("--query", default="", help="Search query")
    gc_parser.add_argument("--limit", type=int, default=20, help="Max results")
    gc_parser.add_argument("--as-of", default="", help="Filter by validity timestamp or ISO date")
    gc_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    gc_parser.set_defaults(func=cmd_get_context)

    # dry-run-diff
    dr_parser = subparsers.add_parser("dry-run-diff", help="Preview diff and syntax check")
    dr_parser.add_argument("--path", required=True, help="Path of file to edit")
    dr_parser.add_argument("--content", required=True, help="Proposed full file content")
    dr_parser.add_argument("--lint", action="store_true", help="Run lint if available")
    dr_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    dr_parser.set_defaults(func=cmd_dry_run_diff)

    # grep-and-read
    gar_parser = subparsers.add_parser("grep-and-read", help="Search then read top files")
    gar_parser.add_argument("query", help="Search query")
    gar_parser.add_argument("--repo", default="", help="Limit search to repo")
    gar_parser.add_argument("--limit", type=int, default=8, help="Max results (default: 8)")
    gar_parser.add_argument("--read-limit", type=int, default=3, help="Files to read (default: 3)")
    gar_parser.add_argument("--file-types", nargs="*", default=[], help="Filter by file extension")
    gar_parser.add_argument("--path-pattern", default="", help="Glob pattern for path matching")
    gar_parser.add_argument("--exclude-patterns", nargs="*", default=[], help="Patterns to exclude")
    gar_parser.add_argument("--recency-boost", action="store_true", help="Boost recently modified files")
    gar_parser.add_argument("--use-regex", action="store_true", help="Treat query as regex")
    gar_parser.add_argument("--case-sensitive", action="store_true", help="Case-sensitive search")
    gar_parser.add_argument("--context-lines", type=int, default=5, help="Snippet lines (default: 5)")
    gar_parser.add_argument("--total-mode", default="exact", choices=["exact", "approx"], help="Total count mode")
    gar_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    gar_parser.set_defaults(func=cmd_grep_and_read)

    # prune
    prune_parser = subparsers.add_parser("prune", help="Prune old data (maintenance)")
    prune_parser.add_argument("--days", type=int, default=None, help="Override TTL days (default: use settings)")
    prune_parser.add_argument("--table", choices=["snippets", "failed_tasks", "contexts"], help="Target specific table")
    prune_parser.add_argument("--workspace", default="", help="Workspace root (default: auto-detect)")
    prune_parser.set_defaults(func=cmd_prune)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "daemon" and not args.daemon_command:
        daemon_parser.print_help()
        return 1

    if hasattr(args, "func"):
        return args.func(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
