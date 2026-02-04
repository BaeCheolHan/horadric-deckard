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
from sari.core.registry import ServerRegistry
from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.mcp.tools.call_graph import build_call_graph
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


def get_daemon_address():
    """Get daemon host and port from environment or defaults."""
    # PRIORITY: SARI_ Only
    host = os.environ.get("SARI_DAEMON_HOST", DEFAULT_HOST)
    port = int(os.environ.get("SARI_DAEMON_PORT", DEFAULT_PORT))
    return host, port


def _package_config_path() -> Path:
    return Path(__file__).parent.parent / "config" / "config.json"


def _load_http_config(workspace_root: str) -> Optional[dict]:
    try:
        from sari.core.workspace import WorkspaceManager
        from sari.core.config import Config
        cfg_path = WorkspaceManager.resolve_config_path(workspace_root)
        return json.loads(Path(cfg_path).read_text(encoding="utf-8")) if Path(cfg_path).exists() else None
    except Exception:
        return None


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
    """Get active HTTP server address with Environment priority ."""
    # 0. Environment Override (Highest Priority for testing/isolation)
    # PRIORITY: SARI_
    env_host = os.environ.get("SARI_HTTP_API_HOST") or os.environ.get("SARI_HTTP_HOST")
    # 3. Fallback to Config
    workspace_root = WorkspaceManager.resolve_workspace_root()
    cfg = _load_http_config(workspace_root) or {}
    host = str(cfg.get("http_api_host", cfg.get("server_host", DEFAULT_HTTP_HOST)))
    port = int(cfg.get("http_api_port", cfg.get("server_port", DEFAULT_HTTP_PORT)))
    if env_host:
        host = env_host
    if os.environ.get("SARI_HTTP_API_PORT") or os.environ.get("SARI_HTTP_PORT"):
        try:
            port = int(os.environ.get("SARI_HTTP_API_PORT") or os.environ.get("SARI_HTTP_PORT"))
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
    if args.daemon_host or args.daemon_port:
        host = args.daemon_host or DEFAULT_HOST
        port = int(args.daemon_port or DEFAULT_PORT)
    else:
        host, port = get_daemon_address()
    workspace_root = WorkspaceManager.resolve_workspace_root()

    if is_daemon_running(host, port):
        pid = read_pid()
        print(f"✅ Daemon already running on {host}:{port}")
        if not pid:
            print("⚠️  PID file missing. Another process may be using this port.")
            print("   Hint: Try a different port: SARI_DAEMON_PORT=47790 sari daemon start -d")
        return 0

    repo_root = Path(__file__).parent.parent.resolve()
    env = os.environ.copy()
    env["SARI_DAEMON_AUTOSTART"] = "1"
    env["SARI_WORKSPACE_ROOT"] = workspace_root
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
            cwd=repo_root,
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
            return cmd_proxy(args)
    except OSError as e:
        if _tcp_blocked(e):
            from sari.mcp.server import main as server_main
            server_main()
            return 0
        # Connection refused etc. We'll try to start daemon below.

    # Try to start daemon in background, then proxy.
    if not is_daemon_running(host, port):
        repo_root = Path(__file__).parent.parent.resolve()
        workspace_root = WorkspaceManager.resolve_workspace_root()
        env = os.environ.copy()
        env["SARI_DAEMON_AUTOSTART"] = "1"
        env["SARI_WORKSPACE_ROOT"] = workspace_root
        subprocess.Popen(
            [sys.executable, "-m", "sari.mcp.daemon"],
            cwd=repo_root,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        for _ in range(30):
            try:
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
        http_running = is_daemon_running(host, port)

        if not daemon_running or not http_running:
            print("❌ Error: Sari services are not fully running.")
            print(f"   Daemon: {'🟢' if daemon_running else '⚫'} {daemon_host}:{daemon_port}")
            print(f"   HTTP:   {'🟢' if http_running else '⚫'} {host}:{port}")
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
