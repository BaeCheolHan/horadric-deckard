#!/usr/bin/env python3
"""
Workspace Registry for Sari Daemon.

Manages shared state (server instance) per workspace with refcount-based lifecycle.
When all clients disconnect from a workspace (refcount=0), resources are cleaned up.
"""
import logging
import threading
from pathlib import Path
from typing import Dict, Optional

from sari.core.http_server import serve_forever
from sari.core.registry import ServerRegistry

logger = logging.getLogger("sari.registry")


class SharedState:
    """Holds the server instance and reference count for a workspace.

    Multiple clients connected to the same workspace share this state,
    avoiding duplicate indexing and DB connections.

    Also manages the dedicated HTTP server for this workspace.
    """

    def __init__(self, workspace_root: str):
        from .server import LocalSearchMCPServer
        self.workspace_root = workspace_root
        self.server = LocalSearchMCPServer(workspace_root)
        self.ref_count = 0
        self.lock = threading.Lock()

        # HTTP Server State
        self.httpd = None
        self.http_port = 0
        self.http_thread = None

        # Initialize Core Server (Loads Config)
        try:
            self.server._ensure_initialized()
            cfg = self.server.cfg

            # Start HTTP Server
            self.httpd, self.http_port = serve_forever(
                host=cfg.server_host,
                port=cfg.server_port,
                db=self.server.db,
                indexer=self.server.indexer,
                version=self.server.SERVER_VERSION,
                workspace_root=self.workspace_root
            )
            logger.info(f"Started HTTP Server for {workspace_root} on port {self.http_port}")

        except Exception as e:
            logger.error(f"Failed to start server components for {workspace_root}: {e}")
            # We don't raise here to allow partial functionality (MCP might work without HTTP?)
            # But usually if init fails, MCP fails too.
            pass

        logger.info(f"Created SharedState for workspace: {workspace_root}")

    def acquire(self) -> int:
        """Increment refcount (client connected)."""
        with self.lock:
            self.ref_count += 1
            logger.debug(f"Acquired {self.workspace_root} (refcount={self.ref_count})")
            return self.ref_count

    def release(self) -> int:
        """Decrement refcount (client disconnected)."""
        with self.lock:
            self.ref_count -= 1
            logger.debug(f"Released {self.workspace_root} (refcount={self.ref_count})")
            return self.ref_count

    def shutdown(self) -> None:
        """Stop indexer, close DB, and shutdown HTTP server."""
        logger.info(f"Shutting down SharedState for {self.workspace_root}")

        # Unregister from Global Registry
        try:
            ServerRegistry().unregister(self.workspace_root)
        except Exception as e:
            logger.error(f"Failed to unregister workspace: {e}")

        # Shutdown HTTP Server
        if self.httpd:
            logger.info("Shutting down HTTP server...")
            self.httpd.shutdown()
            self.httpd.server_close()

        self.server.shutdown()


class Registry:
    """Singleton registry to manage shared server instances.

    Provides refcount-based lifecycle management:
    - get_or_create(): Get or create shared state, refcount++
    - release(): refcount--, cleanup if refcount==0
    """
    _instance: Optional["Registry"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._workspaces: Dict[str, SharedState] = {}
        self._registry_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "Registry":
        """Get the singleton Registry instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = Registry()
                logger.info("Registry singleton created")
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing purposes."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown_all()
            cls._instance = None

    def get_or_create(self, workspace_root: str) -> SharedState:
        """Get existing or create new SharedState for a workspace.

        Automatically increments refcount.

        Args:
            workspace_root: Absolute path to workspace root

        Returns:
            SharedState for the workspace
        """
        resolved_root = str(Path(workspace_root).resolve())

        with self._registry_lock:
            if resolved_root not in self._workspaces:
                self._workspaces[resolved_root] = SharedState(resolved_root)
                logger.info(f"Registered new workspace: {resolved_root}")

            state = self._workspaces[resolved_root]
            state.acquire()
            return state

    def release(self, workspace_root: str) -> None:
        """Release SharedState for a workspace.

        Decrements refcount. If refcount reaches 0, cleans up resources.

        Args:
            workspace_root: Absolute path to workspace root
        """
        resolved_root = str(Path(workspace_root).resolve())

        with self._registry_lock:
            if resolved_root not in self._workspaces:
                logger.warning(f"Attempted to release unknown workspace: {resolved_root}")
                return

            state = self._workspaces[resolved_root]
            remaining = state.release()

            if remaining <= 0:
                state.shutdown()
                del self._workspaces[resolved_root]
                logger.info(f"Unregistered workspace: {resolved_root}")

    def get(self, workspace_root: str) -> Optional[SharedState]:
        """Get SharedState without modifying refcount.

        Args:
            workspace_root: Absolute path to workspace root

        Returns:
            SharedState if exists, None otherwise
        """
        resolved_root = str(Path(workspace_root).resolve())
        with self._registry_lock:
            return self._workspaces.get(resolved_root)

    def list_workspaces(self) -> Dict[str, int]:
        """List all active workspaces with their refcounts.

        Returns:
            Dict mapping workspace_root to refcount
        """
        with self._registry_lock:
            return {ws: state.ref_count for ws, state in self._workspaces.items()}

    def active_count(self) -> int:
        """Get number of active workspaces.

        Returns:
            Number of workspaces with refcount > 0
        """
        with self._registry_lock:
            return len(self._workspaces)

    def shutdown_all(self) -> None:
        """Shutdown all workspaces (for daemon stop)."""
        with self._registry_lock:
            workspace_count = len(self._workspaces)
            for workspace_root, state in list(self._workspaces.items()):
                logger.info(f"Shutting down workspace: {workspace_root}")
                state.shutdown()
            self._workspaces.clear()
        logger.info(f"Registry shutdown complete ({workspace_count} workspaces)")


# Convenience function for getting the registry
def get_registry() -> Registry:
    """Get the global Registry singleton."""
    return Registry.get_instance()