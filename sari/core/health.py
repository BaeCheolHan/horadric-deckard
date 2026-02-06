import sys
import os
import socket
import shutil
import urllib.request
from pathlib import Path
from typing import Dict, List, Any, Optional

from .db import LocalSearchDB
from .workspace import WorkspaceManager
from .server_registry import ServerRegistry

class SariDoctor:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = workspace_root or WorkspaceManager.resolve_workspace_root()
        self.results: List[Dict[str, Any]] = []
        self.common_issues = [
            {"issue": "Permission Denied", "solution": "Check if Sari has read/write access to ~/.local/share/sari and the workspace root."},
            {"issue": "Port Conflict", "solution": "Run 'sari daemon stop' then start with a different port using SARI_DAEMON_PORT=47790."},
            {"issue": "Workspace Not Initialized", "solution": "Run 'sari init' in the workspace root to create the necessary config files."}
        ]

    def _add_result(self, name: str, passed: bool, error: str = "", warn: bool = False, details: Optional[Dict[str, Any]] = None):
        self.results.append({
            "name": name,
            "passed": passed,
            "error": error,
            "warn": warn,
            "details": details or {}
        })

    def check_db(self) -> bool:
        try:
            db_path = WorkspaceManager.get_global_db_path()
            if not db_path.exists():
                self._add_result("DB Existence", False, f"DB not found at {db_path}")
                return False

            db = LocalSearchDB(str(db_path))
            # Check FTS5
            if db.fts_enabled:
                self._add_result("DB FTS5 Support", True)
            else:
                self._add_result("DB FTS5 Support", False, "FTS5 module missing in SQLite")

            # Check Schema
            try:
                cursor = db._read.execute("PRAGMA table_info(symbols)")
                cols = [r["name"] for r in cursor.fetchall()]
                if "end_line" in cols:
                    self._add_result("DB Schema", True)
                else:
                    self._add_result("DB Schema", False, "Column 'end_line' missing in 'symbols'. Run update.")
            except Exception as e:
                self._add_result("DB Schema Check", False, str(e))

            db.close()
            return True
        except Exception as e:
            self._add_result("DB Access", False, str(e))
            return False

    def check_network(self) -> bool:
        try:
            urllib.request.urlopen("https://pypi.org", timeout=3)
            self._add_result("Network Check", True)
            return True
        except Exception as e:
            self._add_result("Network Check", False, f"Unreachable: {e}")
            return False

    def check_port_available(self, port: int = 47777, label: str = "Port") -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            self._add_result(f"{label} {port} Availability", True)
            return True
        except OSError as e:
             self._add_result(f"{label} {port} Availability", False, f"Address in use or missing permission: {e}")
             return False
        finally:
            s.close()

    def check_port_listening(self, port: int, label: str) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                self._add_result(f"{label} {port} Listening", True)
                return True
        except Exception as e:
            self._add_result(f"{label} {port} Listening", False, f"Unreachable: {e}")
            return False

    def check_disk_space(self, min_gb: float = 1.0) -> bool:
        try:
            total, used, free = shutil.disk_usage(self.workspace_root)
            free_gb = free / (1024**3)
            if free_gb < min_gb:
                self._add_result("Disk Space", False, f"Low space: {free_gb:.2f} GB (Min: {min_gb} GB)")
                return False
            else:
                self._add_result("Disk Space", True)
                return True
        except Exception as e:
             self._add_result("Disk Space", False, str(e))
             return False

    def check_daemon(self) -> bool:
        try:
            from sari.mcp.cli import get_daemon_address, is_daemon_running, read_pid
            host, port = get_daemon_address()
            running = is_daemon_running(host, port)
            if running:
                pid = read_pid()
                
                # Enhanced: check metrics if running
                metrics = {}
                try:
                    from sari.mcp.cli import _request_mcp_status
                    m_data = _request_mcp_status(host, port, self.workspace_root)
                    if m_data:
                        metrics = m_data
                except Exception:
                    pass

                self._add_result("Sari Daemon", True, f"Running on {host}:{port} (PID: {pid})", details=metrics)
                return True
            else:
                self._add_result("Sari Daemon", False, "Not running")
                return False
        except Exception as e:
            self._add_result("Daemon Check", False, str(e))
            return False

    def run_all(self):
        self.check_daemon()
        # Environment & Setup
        in_venv = sys.prefix != sys.base_prefix
        self._add_result("Virtualenv", True, "" if in_venv else "Not running in venv (ok)")

        # Runtime checks
        from sari.mcp.cli import get_daemon_address
        daemon_host, daemon_port = get_daemon_address()
        inst = None
        try:
            from sari.core.server_registry import ServerRegistry
            inst = ServerRegistry().resolve_workspace_daemon(self.workspace_root)
        except Exception:
            inst = None
        
        if inst and inst.get("port"):
            self.check_port_listening(int(inst.get("port")), label="Daemon port")
        else:
            self.check_port_listening(daemon_port, label="Daemon port")
        
        self.check_network()
        
        try:
            from sari.core.server_registry import ServerRegistry
            ws_info = ServerRegistry().get_workspace(self.workspace_root)
            if ws_info and ws_info.get("http_port"):
                self.check_port_listening(int(ws_info.get("http_port")), label="HTTP API port")
        except Exception:
            pass

        # Storage checks
        self.check_db()
        self.check_disk_space()

    def get_summary(self) -> Dict[str, Any]:
        passed_count = sum(1 for r in self.results if r["passed"] or r["warn"])
        total_count = len(self.results)
        return {
            "workspace_root": self.workspace_root,
            "passed_count": passed_count,
            "total_count": total_count,
            "results": self.results,
            "common_issues": self.common_issues
        }
