import threading
from typing import Dict, Optional
from pathlib import Path
from .server import LocalSearchMCPServer

class SharedState:
    """Holds the server instance and reference count for a workspace."""
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.server = LocalSearchMCPServer(workspace_root)
        self.ref_count = 0
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            self.ref_count += 1
            # Ensure server is initialized when acquired?
            # server._ensure_initialized() is lazy in the current implementation,
            # but we might want to trigger it here or let the first request do it.

    def release(self) -> int:
        with self.lock:
            self.ref_count -= 1
            return self.ref_count

    def shutdown(self):
        self.server.shutdown()

class Registry:
    """Singleton registry to manage shared server instances."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._workspaces: Dict[str, SharedState] = {}
        self._registry_lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = Registry()
        return cls._instance

    def get_or_create(self, workspace_root: str) -> SharedState:
        # Normalize path
        resolved_root = str(Path(workspace_root).resolve())
        
        with self._registry_lock:
            if resolved_root not in self._workspaces:
                self._workspaces[resolved_root] = SharedState(resolved_root)
            
            state = self._workspaces[resolved_root]
            state.acquire()
            return state

    def release(self, workspace_root: str):
        resolved_root = str(Path(workspace_root).resolve())
        
        with self._registry_lock:
            if resolved_root in self._workspaces:
                state = self._workspaces[resolved_root]
                remaining = state.release()
                
                if remaining <= 0:
                    state.shutdown()
                    del self._workspaces[resolved_root]
