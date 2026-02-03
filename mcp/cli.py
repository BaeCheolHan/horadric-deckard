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
import sys
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Add project root to sys.path for absolute imports
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.workspace import WorkspaceManager
from app.registry import ServerRegistry


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47779
PID_FILE = WorkspaceManager.get_global_data_dir() / "daemon.pid"
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 47777


def get_daemon_address():
    """Get daemon host and port from environment or defaults."""
    host = os.environ.get("DECKARD_DAEMON_HOST", DEFAULT_HOST)
    port = int(os.environ.get("DECKARD_DAEMON_PORT", DEFAULT_PORT))
    return host, port


def _package_config_path() -> Path:
    return Path(__file__).parent.parent / "config" / "config.json"


def _load_http_config(workspace_root: str) -> Optional[dict]:
    try:
        from app.workspace import WorkspaceManager
        from app.config import Config
        cfg_path = WorkspaceManager.resolve_config_path(workspace_root)
        return json.loads(Path(cfg_path).read_text(encoding="utf-8")) if Path(cfg_path).exists() else None
    except Exception:
        return None

def _load_server_info(workspace_root: str) -> Optional[dict]:
    """Legacy server.json location for backward compatibility."""
    server_json = Path(workspace_root) / ".codex" / "tools" / "sari" / "data" / "server.json"
    if not server_json.exists():
        return None
    try:
        return json.loads(server_json.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _enforce_loopback(host: str) -> None:
    if os.environ.get("DECKARD_ALLOW_NON_LOOPBACK") == "1" or os.environ.get("LOCAL_SEARCH_ALLOW_NON_LOOPBACK") == "1":
        return
    if not _is_loopback(host):
        raise RuntimeError(
            f"sari loopback-only: server_host must be 127.0.0.1/localhost/::1 (got={host}). "
            "Set DECKARD_ALLOW_NON_LOOPBACK=1 to override (NOT recommended)."
        )


def _get_http_host_port() -> tuple[str, int]:
    """Get active HTTP server address with Environment priority (v2.7.0)."""
    # 0. Environment Override (Highest Priority for testing/isolation)
    env_host = (
        os.environ.get("DECKARD_HTTP_API_HOST")
        or os.environ.get("DECKARD_HTTP_HOST")
        or os.environ.get("LOCAL_SEARCH_HTTP_HOST")
        or os.environ.get("DECKARD_HOST")
    )
    env_port_raw = (
        os.environ.get("DECKARD_HTTP_API_PORT")
        or os.environ.get("DECKARD_HTTP_PORT")
        or os.environ.get("LOCAL_SEARCH_HTTP_PORT")
        or os.environ.get("DECKARD_PORT")
    )
    env_port = None if env_port_raw in (None, "", "0") else env_port_raw
    if env_host or env_port:
        return str(env_host or DEFAULT_HTTP_HOST), int(env_port or DEFAULT_HTTP_PORT)

    workspace_root = WorkspaceManager.resolve_workspace_root()
    
    # 1. Try Global Registry
    try:
        inst = ServerRegistry().get_instance(workspace_root)
        if inst and inst.get("port"):
            return str(inst.get("host", DEFAULT_HTTP_HOST)), int(inst["port"])
    except Exception:
        pass
    
    # 2. Legacy server.json
    server_info = _load_server_info(workspace_root)
    if server_info:
        try:
            return str(server_info.get("host", DEFAULT_HTTP_HOST)), int(server_info.get("port", DEFAULT_HTTP_PORT))
        except Exception:
            pass

    # 3. Fallback to Config
    cfg = _load_http_config(workspace_root) or {}
    host = str(cfg.get("http_api_host", cfg.get("server_host", DEFAULT_HTTP_HOST)))
    port = int(cfg.get("http_api_port", cfg.get("server_port", DEFAULT_HTTP_PORT)))
    return host, port



def _request_http(path: str, params: dict) -> dict:
    host, port = _get_http_host_port()
    _enforce_loopback(host)
    qs = urllib.parse.urlencode(params)
    url = f"http://{host}:{port}{path}?{qs}"
    with urllib.request.urlopen(url, timeout=3.0) as r:
        return json.loads(r.read().decode("utf-8"))


def is_daemon_running(host: str, port: int) -> bool:
    """Check if daemon is running by attempting connection."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def read_pid() -> Optional[int]:
    """Read PID from pidfile."""
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


def cmd_daemon_start(args):
    """Start the daemon."""
    host, port = get_daemon_address()
    
    if is_daemon_running(host, port):
        print(f"✅ Daemon already running on {host}:{port}")
        return 0
    
    repo_root = Path(__file__).parent.parent.resolve()
    
    if args.daemonize:
        # Start in background
        print(f"Starting daemon on {host}:{port} (background)...")
        
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp.daemon"],
            cwd=repo_root,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
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
            from mcp.daemon import main as daemon_main
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
                os.kill(pid, signal.SIGTERM)
                print(f"Sent SIGTERM to PID {pid}")
            
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
    from mcp.proxy import main as proxy_main
    proxy_main()


def _tcp_blocked(err: OSError) -> bool:
    return getattr(err, "errno", None) in (1, 13)


def cmd_auto(args):
    """Try TCP daemon/proxy first, fallback to STDIO server."""
    host, port = get_daemon_address()

    # Fast path: if TCP is blocked by sandbox, skip daemon/proxy.
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return cmd_proxy(args)
    except OSError as e:
        if _tcp_blocked(e):
            from mcp.server import main as server_main
            server_main()
            return 0
        # Connection refused etc. We'll try to start daemon below.

    # Try to start daemon in background, then proxy.
    if not is_daemon_running(host, port):
        repo_root = Path(__file__).parent.parent.resolve()
        subprocess.Popen(
            [sys.executable, "-m", "mcp.daemon"],
            cwd=repo_root,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            try:
                if is_daemon_running(host, port):
                    break
            except OSError as e:
                if _tcp_blocked(e):
                    from mcp.server import main as server_main
                    server_main()
                    return 0
            time.sleep(0.1)

    if is_daemon_running(host, port):
        return cmd_proxy(args)

    # Final fallback to STDIO server.
    from mcp.server import main as server_main
    server_main()
    return 0


def cmd_status(args):
    """Query HTTP status endpoint."""
    try:
        host, port = _get_http_host_port()
        # Fast check if port is even open
        if not is_daemon_running(host, port):
             print(f"❌ Error: Daemon is not running on {host}:{port}")
             return 1
             
        data = _request_http("/status", {})
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


def cmd_init(args):
    """Initialize workspace with Sari config."""
    workspace_root = Path(args.workspace).expanduser().resolve() if args.workspace else Path(WorkspaceManager.resolve_workspace_root()).resolve()
    cfg_path = Path(WorkspaceManager.resolve_config_path(str(workspace_root)))
    data_dir = workspace_root / ".codex" / "tools" / "sari" / "data"

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    from app.config import Config
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


def main():
    parser = argparse.ArgumentParser(
        prog="sari",
        description="Sari - Local Search MCP Server"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # daemon subcommand
    daemon_parser = subparsers.add_parser("daemon", help="Daemon management")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_command")
    
    # daemon start
    start_parser = daemon_sub.add_parser("start", help="Start daemon")
    start_parser.add_argument("-d", "--daemonize", action="store_true",
                              help="Run in background")
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

    # status subcommand (HTTP)
    status_parser = subparsers.add_parser("status", help="Query HTTP status")
    status_parser.set_defaults(func=cmd_status)

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
