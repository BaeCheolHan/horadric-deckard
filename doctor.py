#!/usr/bin/env python3
"""
Sari Doctor - Health Check.
Checks:
1. DB Connection & FTS5
2. Port availability
3. Workspace paths
4. Environment variables
"""
import sys
import os
import socket
import sqlite3
import shutil
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR # The script is already in the repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sari.core.db import LocalSearchDB
from sari.core.workspace import WorkspaceManager
from sari.core.registry import ServerRegistry
try:
    from sari.mcp.cli import get_daemon_address
except ImportError:
    sys.path.insert(0, str(REPO_ROOT))
    from sari.mcp.cli import get_daemon_address

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

def _resolve_version() -> str:
    try:
        from sari.version import __version__
        return __version__
    except Exception:
        v = (os.environ.get("SARI_VERSION") or "").strip()
        return v or "dev"

def print_status(name: str, passed: bool, error: str = ""):
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    if error:
        print(f"[{status}] {name}: {error}")
    else:
        print(f"[{status}] {name}")

def check_db():
    try:
        ws_root = WorkspaceManager.resolve_workspace_root()
        db_path = WorkspaceManager.get_local_db_path(ws_root)

        if not db_path.exists():
            print_status("DB Existence", False, f"DB not found at {db_path}")
            return False

        db = LocalSearchDB(str(db_path))

        # Check FTS5
        if db.fts_enabled:
            print_status("DB FTS5 Support", True)
        else:
            print_status("DB FTS5 Support", False, "FTS5 module missing in SQLite")

        # Check Schema
        try:
             # Check if symbols table has end_line
            cursor = db._read.execute("PRAGMA table_info(symbols)")
            cols = [r["name"] for r in cursor.fetchall()]
            if "end_line" in cols:
                print_status("DB Schema", True)
            else:
                print_status("DB Schema", False, "Column 'end_line' missing in 'symbols'. Run update.")
        except Exception as e:
            print_status("DB Schema Check", False, str(e))

        db.close()
        return True
    except Exception as e:
        print_status("DB Access", False, str(e))
        return False

def check_network():
    """Check internet connectivity (DNS/TCP)."""
    try:
        # Try connecting to a reliable public DNS (Google) or PyPI
        # Using socket connection to 8.8.8.8:53 (DNS) is standard check
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        print_status("Network Check", True)
        return True
    except OSError as e:
        print_status("Network Check", False, f"Unreachable: {e}")
        return False

def check_port(port: int = 47777, label: str = "Port"):
    """Check if port is available."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        print_status(f"{label} {port} Availability", True)
        return True
    except OSError as e:
         print_status(f"{label} {port} Availability", False, f"Address in use or missing permission: {e}")
         return False
    finally:
        s.close()

def check_disk_space(min_gb: float = 1.0):
    """Check if free disk space is sufficient."""
    try:
        # Check space of current workspace or home
        ws_root = WorkspaceManager.resolve_workspace_root()
        total, used, free = shutil.disk_usage(ws_root)
        free_gb = free / (1024**3)
        if free_gb < min_gb:
            print_status("Disk Space", False, f"Low space: {free_gb:.2f} GB (Min: {min_gb} GB)")
            return False
        else:
            print_status("Disk Space", True)
            return True
    except Exception as e:
         print_status("Disk Space", False, str(e))
         return False

def check_daemon():
    """Check if Sari Daemon is running."""
    from sari.mcp.cli import get_daemon_address, is_daemon_running, read_pid
    host, port = get_daemon_address()
    running = is_daemon_running(host, port)
    if running:
        pid = read_pid()
        print_status("Sari Daemon", True, f"Running on {host}:{port} (PID: {pid})")
        return True
    else:
        print_status("Sari Daemon", False, "Not running")
        return False

def run_doctor():
    print(f"\n{YELLOW}Sari Doctor (v{_resolve_version()}){RESET}")
    print("==================================================")

    ws_root = WorkspaceManager.resolve_workspace_root()
    print(f"Workspace Root: {ws_root}\n")

    # 1. Environment & Setup
    print(f"{YELLOW}[Setup]{RESET}")
    in_venv = sys.prefix != sys.base_prefix
    print_status("Virtualenv", True, "" if in_venv else "Not running in venv (ok)")

    # 2. Daemon & Network
    print(f"\n{YELLOW}[Runtime]{RESET}")
    check_daemon()
    daemon_host, daemon_port = get_daemon_address()
    check_port(daemon_port, label="Daemon port")
    check_network()
    try:
        inst = ServerRegistry().get_instance(ws_root)
        if inst and inst.get("port"):
            check_port(int(inst.get("port")), label="HTTP API port")
    except Exception:
        pass

    # 3. DB & Storage
    print(f"\n{YELLOW}[Storage]{RESET}")
    check_db()
    check_disk_space()

    print("\n==================================================")
    print("💡 Tip: Run 'init' to setup or 'daemon start' to run.")
    print(f"Run '{sys.executable} install.py' if core modules are missing.")

if __name__ == "__main__":
    run_doctor()
