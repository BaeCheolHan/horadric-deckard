#!/usr/bin/env python3
"""
Doctor tool for Local Search MCP Server.
Returns structured diagnostics (no ANSI/prints).
"""
import json
import os
import os
import socket
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    from app.db import LocalSearchDB
    from app.config import Config
    from app.workspace import WorkspaceManager
    from app.registry import ServerRegistry
    from mcp.cli import get_daemon_address, is_daemon_running, read_pid
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.db import LocalSearchDB
    from app.config import Config
    from app.workspace import WorkspaceManager
    from app.registry import ServerRegistry
    from mcp.cli import get_daemon_address, is_daemon_running, read_pid


def _result(name: str, passed: bool, error: str = "") -> dict[str, Any]:
    return {"name": name, "passed": passed, "error": error}


def _check_db(ws_root: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cfg_path = WorkspaceManager.resolve_config_path(ws_root)
    cfg = Config.load(cfg_path, workspace_root_override=ws_root)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        results.append(_result("DB Existence", False, f"DB not found at {db_path}"))
        return results

    try:
        db = LocalSearchDB(str(db_path))
    except Exception as e:
        results.append(_result("DB Access", False, str(e)))
        return results

    results.append(_result("DB FTS5 Support", bool(db.fts_enabled), "FTS5 module missing in SQLite" if not db.fts_enabled else ""))
    try:
        cursor = db._read.execute("PRAGMA table_info(symbols)")
        cols = [r["name"] for r in cursor.fetchall()]
        if "end_line" in cols:
            results.append(_result("DB Schema v2.7.0", True))
        else:
            results.append(_result("DB Schema v2.7.0", False, "Column 'end_line' missing in 'symbols'. Run update."))
    except Exception as e:
        results.append(_result("DB Schema Check", False, str(e)))
    finally:
        try:
            db.close()
        except Exception:
            pass

    return results


def _check_port(port: int, label: str) -> dict[str, Any]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return _result(f"{label} Port {port} Availability", True)
    except OSError as e:
        return _result(f"{label} Port {port} Availability", False, f"Address in use or missing permission: {e}")
    finally:
        try:
            s.close()
        except Exception:
            pass


def _check_network() -> dict[str, Any]:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return _result("Network Check", True)
    except OSError as e:
        return _result("Network Check", False, f"Unreachable: {e}")


def _check_disk_space(ws_root: str, min_gb: float) -> dict[str, Any]:
    try:
        total, used, free = shutil.disk_usage(ws_root)
        free_gb = free / (1024**3)
        if free_gb < min_gb:
            return _result("Disk Space", False, f"Low space: {free_gb:.2f} GB (Min: {min_gb} GB)")
        return _result("Disk Space", True)
    except Exception as e:
        return _result("Disk Space", False, str(e))


def _check_daemon() -> dict[str, Any]:
    host, port = get_daemon_address()
    running = is_daemon_running(host, port)
    if running:
        pid = read_pid()
        return _result("Sari Daemon", True, f"Running on {host}:{port} (PID: {pid})")
    return _result("Sari Daemon", False, "Not running")


def _check_search_first_usage(usage: Dict[str, Any], mode: str) -> dict[str, Any]:
    violations = int(usage.get("read_without_search", 0))
    searches = int(usage.get("search", 0))
    symbol_searches = int(usage.get("search_symbols", 0))
    if violations == 0:
        return _result("Search-First Usage", True, "")
    policy = mode if mode in {"off", "warn", "enforce"} else "unknown"
    error = (
        f"Search-first policy {policy}: {violations} read call(s) without prior search "
        f"(search={searches}, search_symbols={symbol_searches})."
    )
    return _result("Search-First Usage", False, error)


def execute_doctor(args: Dict[str, Any]) -> Dict[str, Any]:
    ws_root = WorkspaceManager.resolve_workspace_root()

    include_network = bool(args.get("include_network", True))
    include_port = bool(args.get("include_port", True))
    include_db = bool(args.get("include_db", True))
    include_disk = bool(args.get("include_disk", True))
    include_daemon = bool(args.get("include_daemon", True))
    include_venv = bool(args.get("include_venv", True))
    include_marker = bool(args.get("include_marker", False))
    port = int(args.get("port", 0))
    min_disk_gb = float(args.get("min_disk_gb", 1.0))

    results: list[dict[str, Any]] = []

    if include_venv:
        in_venv = sys.prefix != sys.base_prefix
        results.append(_result("Virtualenv", True, "" if in_venv else "Not running in venv (ok)"))

    if include_marker:
        results.append(_result("Workspace Marker (.codex-root)", True, "Marker check deprecated"))

    if include_daemon:
        results.append(_check_daemon())

    if include_port:
        daemon_host, daemon_port = get_daemon_address()
        results.append(_check_port(daemon_port, "Daemon"))
        http_port = 0
        try:
            inst = ServerRegistry().get_instance(ws_root)
            if inst and inst.get("port"):
                http_port = int(inst.get("port"))
        except Exception:
            http_port = 0
        if not http_port:
            try:
                cfg_path = WorkspaceManager.resolve_config_path(ws_root)
                cfg = Config.load(cfg_path, workspace_root_override=ws_root)
                http_port = int(cfg.http_api_port)
            except Exception:
                http_port = 0
        if port:
            http_port = port
        if http_port:
            results.append(_check_port(http_port, "HTTP"))

    if include_network:
        results.append(_check_network())

    if include_db:
        results.extend(_check_db(ws_root))

    if include_disk:
        results.append(_check_disk_space(ws_root, min_disk_gb))

    usage = args.get("search_usage")
    if isinstance(usage, dict):
        mode = str(args.get("search_first_mode", "unknown"))
        results.append(_check_search_first_usage(usage, mode))

    output = {
        "workspace_root": ws_root,
        "results": results,
    }

    compact = str(os.environ.get("DECKARD_RESPONSE_COMPACT") or "1").strip().lower() not in {"0", "false", "no", "off"}
    payload = json.dumps(output, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(output, ensure_ascii=False, indent=2)
    try:
        from mcp.tools._util import mcp_response, pack_header, pack_line, pack_encode_text
    except Exception:
        from _util import mcp_response, pack_header, pack_line, pack_encode_text

    def build_pack() -> str:
        lines = [pack_header("doctor", {}, returned=1)]
        lines.append(pack_line("t", single_value=pack_encode_text(payload)))
        return "\n".join(lines)

    return mcp_response(
        "doctor",
        build_pack,
        lambda: {"content": [{"type": "text", "text": payload}]},
    )
