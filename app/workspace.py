#!/usr/bin/env python3
"""
Workspace management for Local Search MCP Server.
Handles workspace detection and global path resolution.
"""
import os
from pathlib import Path
from typing import Optional


class WorkspaceManager:
    """Manages workspace detection and global paths."""
    
    @staticmethod
    def resolve_workspace_root(root_uri: Optional[str] = None) -> str:
        """
        Unified resolver for workspace root directory.
        
        Priority:
        1. root_uri parameter (from MCP initialize)
        2. DECKARD_WORKSPACE_ROOT environment variable
        3. LOCAL_SEARCH_WORKSPACE_ROOT environment variable
        4. Search for .codex-root marker from cwd upward
        5. Fallback to cwd
        
        Args:
            root_uri: Optional URI from MCP initialize (file:// prefix will be stripped)
        
        Returns:
            Absolute path to workspace root
        """
        # 1. Use root_uri if provided
        if root_uri:
            if root_uri.startswith("file://"):
                path = root_uri[7:]
            else:
                path = root_uri
            if path and Path(path).exists():
                return str(Path(path).resolve())
        
        # 2. Check environment variables
        for env_key in ["DECKARD_WORKSPACE_ROOT", "LOCAL_SEARCH_WORKSPACE_ROOT"]:
            val = (os.environ.get(env_key) or "").strip()
            if not val:
                continue
            
            if val == "${cwd}":
                return str(Path.cwd())
            
            p = Path(os.path.expanduser(val))
            if p.exists():
                return str(p.resolve())
        
        # 3. Search for .codex-root marker
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / ".codex-root").exists():
                return str(parent)
        
        # 4. Fallback to cwd
        return str(cwd)

    @staticmethod
    def detect_workspace(root_uri: Optional[str] = None) -> str:
        """Legacy alias for resolve_workspace_root."""
        return WorkspaceManager.resolve_workspace_root(root_uri)

    @staticmethod
    def resolve_config_path(workspace_root: str) -> str:
        """
        Resolve config path with unified priority.
        
        Priority:
        1. DECKARD_CONFIG environment variable
        2. LOCAL_SEARCH_CONFIG environment variable
        3. <workspace_root>/.codex/tools/deckard/config/config.json
        4. Packaged default config
        """
        for env_key in ["DECKARD_CONFIG", "LOCAL_SEARCH_CONFIG"]:
            val = (os.environ.get(env_key) or "").strip()
            if val:
                p = Path(os.path.expanduser(val))
                if p.exists():
                    return str(p.resolve())
        
        workspace_cfg = Path(workspace_root) / ".codex" / "tools" / "deckard" / "config" / "config.json"
        if workspace_cfg.exists():
            return str(workspace_cfg)
            
        # Fallback to packaged config (install dir)
        package_root = Path(__file__).resolve().parents[1]
        return str(package_root / "config" / "config.json")
    
    @staticmethod
    def get_global_data_dir() -> Path:
        """Get global data directory: ~/.local/share/deckard/ (or AppData/Local on Win)"""
        if os.name == 'nt':
            return Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))) / "horadric-deckard"
        return Path.home() / ".local" / "share" / "deckard"
    
    @staticmethod
    def get_global_db_path() -> Path:
        """Get global DB path: ~/.local/share/deckard/index.db (Opt-in only)"""
        return WorkspaceManager.get_global_data_dir() / "index.db"

    @staticmethod
    def get_local_db_path(workspace_root: str) -> Path:
        """Get workspace-local DB path: .codex/tools/deckard/data/index.db"""
        return Path(workspace_root) / ".codex" / "tools" / "deckard" / "data" / "index.db"
    
    @staticmethod
    def get_global_log_dir() -> Path:
        """Get global log directory, with env override."""
        for env_key in ["DECKARD_LOG_DIR", "LOCAL_SEARCH_LOG_DIR"]:
            val = (os.environ.get(env_key) or "").strip()
            if val:
                return Path(os.path.expanduser(val)).resolve()
        return WorkspaceManager.get_global_data_dir() / "logs"
