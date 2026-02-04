import json
import os
import time
import socket
from pathlib import Path
from typing import Dict, Optional, Any, Iterable

# Cross-platform file locking
IS_WINDOWS = os.name == "nt"
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
    Registry v2 (SSOT):
      - daemons: boot_id -> {host, port, pid, start_ts, last_seen_ts, draining, version}
      - workspaces: workspace_root -> {boot_id, last_active_ts, http_port, http_host}
    """

    VERSION = "2.0"

    def __init__(self):
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        if not REGISTRY_FILE.exists():
            self._save(self._empty())

    def _empty(self) -> Dict[str, Any]:
        return {"version": self.VERSION, "daemons": {}, "workspaces": {}}

    def _normalize_workspace_root(self, workspace_root: str) -> str:
        return str(Path(workspace_root).expanduser().resolve())

    def _safe_load(self, f) -> Dict[str, Any]:
        try:
            data = json.load(f)
        except Exception:
            data = {}
        return self._ensure_v2(data)

    def _ensure_v2(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return self._empty()
        version = data.get("version")
        if version == self.VERSION and "daemons" in data and "workspaces" in data:
            return data

        # Migrate legacy schema (v1)
        if "instances" in data:
            now = time.time()
            migrated = self._empty()
            for ws, info in (data.get("instances") or {}).items():
                try:
                    ws_norm = self._normalize_workspace_root(ws)
                except Exception:
                    ws_norm = ws
                pid = info.get("pid")
                port = info.get("port")
                boot_id = f"legacy-{pid}-{port}"
                migrated["daemons"][boot_id] = {
                    "host": "127.0.0.1",
                    "port": port,
                    "pid": pid,
                    "start_ts": info.get("start_ts") or now,
                    "last_seen_ts": now,
                    "draining": False,
                    "version": info.get("version") or "legacy",
                }
                migrated["workspaces"][ws_norm] = {
                    "boot_id": boot_id,
                    "last_active_ts": now,
                }
            return migrated

        return self._empty()

    def _load(self) -> Dict[str, Any]:
        """Load registry with shared lock."""
        try:
            with open(REGISTRY_FILE, "r") as f:
                if not IS_WINDOWS:
                    fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    return self._safe_load(f)
                finally:
                    if not IS_WINDOWS:
                        fcntl.flock(f, fcntl.LOCK_UN)
        except FileNotFoundError:
            return self._empty()

    def _save(self, data: Dict[str, Any]):
        """Save registry with exclusive lock."""
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_FILE, "w") as f:
            if not IS_WINDOWS:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2)
            finally:
                if not IS_WINDOWS:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def _update(self, updater) -> None:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_FILE, "a+") as f:
            if not IS_WINDOWS:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                data = self._safe_load(f)
                updater(data)
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()
            finally:
                if not IS_WINDOWS:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def _is_process_alive(self, pid: Optional[int]) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)  # Signal 0 checks existence
            return True
        except OSError:
            return False

    def _prune_dead_locked(self, data: Dict[str, Any]) -> None:
        daemons = data.get("daemons", {})
        workspaces = data.get("workspaces", {})
        dead = [boot_id for boot_id, info in daemons.items()
                if not self._is_process_alive(info.get("pid"))]
        for boot_id in dead:
            daemons.pop(boot_id, None)
        if dead:
            workspaces = {
                ws: info for ws, info in workspaces.items()
                if info.get("boot_id") not in dead
            }
        data["daemons"] = daemons
        data["workspaces"] = workspaces

    def register_daemon(self, boot_id: str, host: str, port: int, pid: int, version: str = "") -> None:
        """Register a running daemon."""
        def _upd(data):
            self._prune_dead_locked(data)
            daemons = data.get("daemons", {})
            daemons[boot_id] = {
                "host": host,
                "port": port,
                "pid": pid,
                "start_ts": daemons.get(boot_id, {}).get("start_ts") or time.time(),
                "last_seen_ts": time.time(),
                "draining": bool(daemons.get(boot_id, {}).get("draining", False)),
                "version": version or daemons.get(boot_id, {}).get("version", ""),
            }
            data["daemons"] = daemons
            data["version"] = self.VERSION
        self._update(_upd)

    def touch_daemon(self, boot_id: str) -> None:
        """Update last_seen for daemon."""
        def _upd(data):
            daemons = data.get("daemons", {})
            if boot_id in daemons:
                daemons[boot_id]["last_seen_ts"] = time.time()
            data["daemons"] = daemons
            data["version"] = self.VERSION
        self._update(_upd)

    def set_daemon_draining(self, boot_id: str, draining: bool = True) -> None:
        def _upd(data):
            daemons = data.get("daemons", {})
            if boot_id in daemons:
                daemons[boot_id]["draining"] = bool(draining)
            data["daemons"] = daemons
            data["version"] = self.VERSION
        self._update(_upd)

    def unregister_daemon(self, boot_id: str) -> None:
        def _upd(data):
            daemons = data.get("daemons", {})
            if boot_id in daemons:
                daemons.pop(boot_id, None)
            workspaces = data.get("workspaces", {})
            workspaces = {
                ws: info for ws, info in workspaces.items()
                if info.get("boot_id") != boot_id
            }
            data["daemons"] = daemons
            data["workspaces"] = workspaces
            data["version"] = self.VERSION
        self._update(_upd)

    def set_workspace(self, workspace_root: str, boot_id: str,
                      http_port: Optional[int] = None, http_host: Optional[str] = None) -> Optional[str]:
        """Bind workspace to daemon (returns previous boot_id if changed)."""
        ws = self._normalize_workspace_root(workspace_root)
        prev_boot = None

        def _upd(data):
            nonlocal prev_boot
            self._prune_dead_locked(data)
            workspaces = data.get("workspaces", {})
            prev_boot = workspaces.get(ws, {}).get("boot_id")
            payload = dict(workspaces.get(ws, {}))
            payload["boot_id"] = boot_id
            payload["last_active_ts"] = time.time()
            if http_port is not None:
                payload["http_port"] = int(http_port)
            if http_host:
                payload["http_host"] = str(http_host)
            workspaces[ws] = payload
            data["workspaces"] = workspaces
            data["version"] = self.VERSION
            # If ownership changed, mark previous daemon as draining.
            if prev_boot and prev_boot != boot_id:
                daemons = data.get("daemons", {})
                if prev_boot in daemons:
                    daemons[prev_boot]["draining"] = True
                data["daemons"] = daemons
        self._update(_upd)
        return prev_boot

    def touch_workspace(self, workspace_root: str) -> None:
        ws = self._normalize_workspace_root(workspace_root)

        def _upd(data):
            workspaces = data.get("workspaces", {})
            if ws in workspaces:
                workspaces[ws]["last_active_ts"] = time.time()
            data["workspaces"] = workspaces
            data["version"] = self.VERSION
        self._update(_upd)

    def set_workspace_http(self, workspace_root: str, http_port: int, http_host: Optional[str] = None) -> None:
        ws = self._normalize_workspace_root(workspace_root)

        def _upd(data):
            workspaces = data.get("workspaces", {})
            if ws in workspaces:
                workspaces[ws]["http_port"] = int(http_port)
                if http_host:
                    workspaces[ws]["http_host"] = str(http_host)
            data["workspaces"] = workspaces
            data["version"] = self.VERSION
        self._update(_upd)

    def unregister_workspace(self, workspace_root: str, boot_id: Optional[str] = None) -> None:
        ws = self._normalize_workspace_root(workspace_root)

        def _upd(data):
            workspaces = data.get("workspaces", {})
            if ws in workspaces:
                if boot_id and workspaces[ws].get("boot_id") != boot_id:
                    return
                workspaces.pop(ws, None)
            data["workspaces"] = workspaces
            data["version"] = self.VERSION
        self._update(_upd)

    def get_daemon(self, boot_id: str) -> Optional[Dict[str, Any]]:
        data = self._load()
        daemon = (data.get("daemons") or {}).get(boot_id)
        if not daemon:
            return None
        if not self._is_process_alive(daemon.get("pid")):
            self.unregister_daemon(boot_id)
            return None
        return daemon

    def get_workspace(self, workspace_root: str) -> Optional[Dict[str, Any]]:
        ws = self._normalize_workspace_root(workspace_root)
        data = self._load()
        return (data.get("workspaces") or {}).get(ws)

    def list_workspaces_for_boot(self, boot_id: str) -> Iterable[str]:
        data = self._load()
        workspaces = data.get("workspaces", {})
        return [ws for ws, info in workspaces.items() if info.get("boot_id") == boot_id]

    def resolve_workspace_daemon(self, workspace_root: str) -> Optional[Dict[str, Any]]:
        ws = self._normalize_workspace_root(workspace_root)
        data = self._load()
        workspaces = data.get("workspaces", {})
        info = workspaces.get(ws)
        if not info:
            return None
        boot_id = info.get("boot_id")
        daemon = (data.get("daemons") or {}).get(boot_id)
        if not daemon:
            self.unregister_workspace(ws)
            return None
        if not self._is_process_alive(daemon.get("pid")):
            self.unregister_daemon(boot_id)
            return None
        merged = dict(daemon)
        merged["boot_id"] = boot_id
        return merged

    def get_instance(self, workspace_root: str) -> Optional[Dict[str, Any]]:
        """Backward compatible alias for resolve_workspace_daemon."""
        return self.resolve_workspace_daemon(workspace_root)

    def register(self, workspace_root: str, port: int, pid: int) -> None:
        """Backward compatible registry (legacy)."""
        boot_id = f"legacy-{pid}-{port}"
        self.register_daemon(boot_id=boot_id, host="127.0.0.1", port=port, pid=pid, version="legacy")
        self.set_workspace(workspace_root, boot_id)

    def unregister(self, workspace_root: str) -> None:
        """Backward compatible unregister."""
        self.unregister_workspace(workspace_root)

    def find_free_port(self, start_port: int = 47777, max_port: int = 65535) -> int:
        """Find a port not in use by other instances AND OS."""
        data = self._load()
        used_ports = {
            info.get("port")
            for info in (data.get("daemons") or {}).values()
            if self._is_process_alive(info.get("pid"))
        }

        for port in range(start_port, max_port + 1):
            if port in used_ports:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", port))
                    return port
            except OSError:
                continue

        raise RuntimeError("No free ports available")
