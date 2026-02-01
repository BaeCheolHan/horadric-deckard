#!/usr/bin/env python3
"""
Horadric Doctor - Health Check for Deckard.
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
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import LocalSearchDB
from app.workspace import WorkspaceManager

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

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
             # Check if symbols table has end_line (Schema 2.7.0)
            cursor = db._read.execute("PRAGMA table_info(symbols)")
            cols = [r["name"] for r in cursor.fetchall()]
            if "end_line" in cols:
                print_status("DB Schema v2.7.0", True)
            else:
                print_status("DB Schema v2.7.0", False, "Column 'end_line' missing in 'symbols'. Run update.")
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

def check_port(port: int = 47777):
    """Check if port is available."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        print_status(f"Port {port} Availability", True)
        return True
    except OSError as e:
         print_status(f"Port {port} Availability", False, f"Address in use or missing permission: {e}")
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

def check_marker():
    """Check if workspace marker exists."""
    ws_root = WorkspaceManager.resolve_workspace_root()
    marker = Path(ws_root) / ".codex-root"
    if marker.exists():
        print_status("Workspace Marker (.codex-root)", True)
        return True
    else:
        print_status("Workspace Marker (.codex-root)", False, f"Marker missing at {ws_root}. Run 'init' first.")
        return False

def check_daemon():
    """Check if Deckard Daemon is running."""
    from mcp.cli import get_daemon_address, is_daemon_running, read_pid
    host, port = get_daemon_address()
    running = is_daemon_running(host, port)
    if running:
        pid = read_pid()
        print_status("Deckard Daemon", True, f"Running on {host}:{port} (PID: {pid})")
        return True
    else:
        print_status("Deckard Daemon", False, "Not running")
        return False

def run_doctor():
    print(f"\n{YELLOW}Horadric Deckard Doctor (v{os.environ.get('DECKARD_VERSION', 'dev')}){RESET}")
    print("==================================================")
    
    ws_root = WorkspaceManager.resolve_workspace_root()
    print(f"Workspace Root: {ws_root}\n")
    
    # 1. Environment & Setup
    print(f"{YELLOW}[Setup]{RESET}")
    in_venv = sys.prefix != sys.base_prefix
    print_status("Virtualenv", in_venv, "" if in_venv else "Not running in venv")
    check_marker()
    
    # 2. Daemon & Network
    print(f"\n{YELLOW}[Runtime]{RESET}")
    check_daemon()
    check_port(47800) # TCP Daemon port
    check_network()
    
    # 3. DB & Storage
    print(f"\n{YELLOW}[Storage]{RESET}")
    check_db()
    check_disk_space()
    
    print("\n==================================================")
    print("💡 Tip: Run 'init' to setup or 'daemon start' to run.")
    print(f"Run '{sys.executable} install.py' if core modules are missing.")

if __name__ == "__main__":
    run_doctor()
