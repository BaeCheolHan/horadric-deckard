import json
import os
import sys
import time
import socket
from pathlib import Path
from typing import Dict, Optional, Any

# Cross-platform file locking
IS_WINDOWS = os.name == 'nt'
if not IS_WINDOWS:
    import fcntl

# Local Standard Path
if os.environ.get("SARI_REGISTRY_FILE"):
    REGISTRY_FILE = Path(os.environ["SARI_REGISTRY_FILE"]).resolve()
    REGISTRY_DIR = REGISTRY_FILE.parent
else:
    REGISTRY_DIR = Path.home() / ".local" / "share" / "sari"
    REGISTRY_FILE = REGISTRY_DIR / "server.json"

class ServerRegistry:
    """
    Manages the 'server.json' registry for Sari Daemons.
    Maps Workspace Root Paths -> {Port, PID, Status}.
    Thread/Process safe via fcntl locking.
    """

    def __init__(self):
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        if not REGISTRY_FILE.exists():
            self._write_empty()

    def _write_empty(self):
        with open(REGISTRY_FILE, "w") as f:
            json.dump({"version": "1.0", "instances": {}}, f)

    def _load(self) -> Dict[str, Any]:
        """Load registry with lock."""
        try:
            with open(REGISTRY_FILE, "r+") as f:
                if not IS_WINDOWS:
                    fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {"version": "1.0", "instances": {}}
                finally:
                    if not IS_WINDOWS:
                        fcntl.flock(f, fcntl.LOCK_UN)
        except FileNotFoundError:
            return {"version": "1.0", "instances": {}}

    def _save(self, data: Dict[str, Any]):
        """Save registry with lock."""
        with open(REGISTRY_FILE, "w") as f:
            if not IS_WINDOWS:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2)
            finally:
                if not IS_WINDOWS:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def register(self, workspace_root: str, port: int, pid: int) -> None:
        """Register a running daemon."""
        # Normalize path
        workspace_root = str(Path(workspace_root).resolve())

        # Read-Modify-Write loop needs EX lock on read too if strict,
        # but simple file lock wrapper is okay for low contention.
        # Ideally open "r+" with LOCK_EX, read, seek 0, write, truncate.

        with open(REGISTRY_FILE, "r+") as f:
            if not IS_WINDOWS:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                try:
                    data = json.load(f)
                except:
                    data = {"version": "1.0", "instances": {}}

                instances = data.get("instances", {})
                instances[workspace_root] = {
                    "port": port,
                    "pid": pid,
                    "start_ts": time.time(),
                    "status": "active"
                }
                data["instances"] = instances

                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()
            finally:
                if not IS_WINDOWS:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def unregister(self, workspace_root: str) -> None:
        """Remove a daemon (on shutdown)."""
        workspace_root = str(Path(workspace_root).resolve())

        with open(REGISTRY_FILE, "r+") as f:
            if not IS_WINDOWS:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                try:
                    data = json.load(f)
                except:
                    return

                instances = data.get("instances", {})
                if workspace_root in instances:
                    del instances[workspace_root]
                    data["instances"] = instances

                    f.seek(0)
                    json.dump(data, f, indent=2)
                    f.truncate()
            finally:
                if not IS_WINDOWS:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def get_instance(self, workspace_root: str) -> Optional[Dict[str, Any]]:
        """Get info for a workspace daemon. Checks liveness."""
        workspace_root = str(Path(workspace_root).resolve())
        data = self._load()
        inst = data.get("instances", {}).get(workspace_root)

        if not inst:
            return None

        # Check if process is actually alive
        pid = inst.get("pid")
        if not self._is_process_alive(pid):
            # Lazy cleanup? Or just return None.
            # Let's clean up lazily if we have the lock, but here we just have read lock (via load).
            # Just return None, cleanup happens on next write or dedicated gc.
            return None

        return inst

    def _is_process_alive(self, pid: int) -> bool:
        if not pid: return False
        try:
            os.kill(pid, 0) # Signal 0 checks existence
            return True
        except OSError:
            return False

    def find_free_port(self, start_port: int = 47777, max_port: int = 65535) -> int:
        """Find a port not in use by other instances AND OS."""
        # 1. Get used ports from registry
        data = self._load()
        used_ports = {
            info["port"] for info in data.get("instances", {}).values()
            if self._is_process_alive(info.get("pid"))
        }

        for port in range(start_port, max_port + 1):
            if port in used_ports:
                continue

            # 2. Check OS binding
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", port))
                    return port
            except OSError:
                continue

        raise RuntimeError("No free ports available")