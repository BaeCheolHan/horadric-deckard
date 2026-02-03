#!/usr/bin/env python3
"""
Workspace management for Local Search MCP Server.
Handles workspace detection and global path resolution.
"""
import os
import hashlib
from pathlib import Path
from typing import Optional


class WorkspaceManager:
    """Manages workspace detection and global paths."""

    @staticmethod
    def _normalize_path(path: str, follow_symlinks: bool) -> str:
        expanded = os.path.expanduser(path)
        if follow_symlinks:
            normalized = os.path.realpath(expanded)
        else:
            normalized = os.path.abspath(expanded)
        if os.name == "nt":
            normalized = normalized.lower()
        return normalized.rstrip(os.sep)

    @staticmethod
    def root_id(path: str) -> str:
        """Stable root id derived from normalized path."""
        norm = WorkspaceManager._normalize_path(path, follow_symlinks=False)
        digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
        return f"root-{digest}"

    @staticmethod
    def resolve_workspace_roots(
        root_uri: Optional[str] = None,
        roots_json: Optional[str] = None,
        roots_env: Optional[dict] = None,
        config_roots: Optional[list] = None
    ) -> list[str]:
        """
        Resolve multiple workspace roots with priority, normalization, and deduplication.
        
        Priority (Union & Merge):
        1. root_uri (MCP initialize param) - highest priority
        2. DECKARD_ROOTS_JSON
        3. DECKARD_ROOT_1..N
        4. config.roots
        5. DECKARD_WORKSPACE_ROOT (legacy)
        6. LOCAL_SEARCH_WORKSPACE_ROOT (legacy)
        7. .codex-root marker search (from cwd upward)
        8. Fallback to cwd
        
        Returns:
            List of absolute, normalized paths.
        """
        candidates = []
        env_vars = roots_env if roots_env is not None else os.environ
        follow_symlinks = (env_vars.get("DECKARD_FOLLOW_SYMLINKS", "0").strip().lower() in ("1", "true", "yes", "on"))

        # 1. root_uri (override)
        if root_uri:
            uri_path = root_uri[7:] if root_uri.startswith("file://") else root_uri
            try:
                if uri_path and Path(os.path.expanduser(uri_path)).exists():
                    candidates.append(uri_path)
            except Exception:
                pass
        
        # 2. DECKARD_ROOTS_JSON
        import json
        json_str = roots_json or env_vars.get("DECKARD_ROOTS_JSON", "")
        if json_str:
            try:
                loaded = json.loads(json_str)
                if isinstance(loaded, list):
                    candidates.extend(str(x) for x in loaded if x)
            except Exception:
                pass
                
        # 3. DECKARD_ROOT_1..N
        for k, v in env_vars.items():
            if k.startswith("DECKARD_ROOT_") and k[13:].isdigit():
                if v and v.strip():
                    candidates.append(v.strip())
                    
        # 4. config.roots
        if config_roots:
            candidates.extend(str(x) for x in config_roots if x)
            
        # 5. Legacy DECKARD_WORKSPACE_ROOT (Higher priority than LOCAL_SEARCH)
        legacy_val = (env_vars.get("DECKARD_WORKSPACE_ROOT") or "").strip()
        if legacy_val:
            if legacy_val == "${cwd}":
                candidates.append(os.getcwd())
            else:
                candidates.append(legacy_val)

        # 6. Legacy LOCAL_SEARCH_WORKSPACE_ROOT
        ls_val = (env_vars.get("LOCAL_SEARCH_WORKSPACE_ROOT") or "").strip()
        if ls_val:
            if ls_val == "${cwd}":
                candidates.append(os.getcwd())
            else:
                candidates.append(ls_val)
                
        # 7. Search for .codex-root marker (If no candidates found yet)
        if not candidates:
            cwd = Path.cwd()
            for parent in [cwd] + list(cwd.parents):
                if (parent / ".codex-root").exists():
                    candidates.append(str(parent))
                    break
        
        # 8. Fallback to cwd
        if not candidates:
            candidates.append(os.getcwd())
            
        # Normalization
        resolved_paths = []
        for p in candidates:
            try:
                abs_path = WorkspaceManager._normalize_path(p, follow_symlinks=follow_symlinks)
                if abs_path not in resolved_paths:
                    resolved_paths.append(abs_path)
            except Exception:
                continue
                
        # Inclusion check while preserving priority order (first seen wins)
        final_roots: list[str] = []
        for p in resolved_paths:
            is_covered = False
            p_path = Path(p)
            for existing in final_roots:
                try:
                    if p_path == Path(existing) or Path(existing) in p_path.parents:
                        is_covered = True
                        break
                    if p.startswith(existing + os.sep):
                        is_covered = True
                        break
                except Exception:
                    continue
            if not is_covered:
                final_roots.append(p)

        return final_roots

    @staticmethod
    def resolve_workspace_root(root_uri: Optional[str] = None) -> str:
        """
        Unified resolver for workspace root directory.
        Legacy wrapper around resolve_workspace_roots.
        Returns the first resolved root.
        """
        roots = WorkspaceManager.resolve_workspace_roots(root_uri=root_uri)
        return roots[0] if roots else str(Path.cwd())

    @staticmethod
    def is_path_allowed(path: str, roots: list[str]) -> bool:
        """Check if path is within any of the roots."""
        try:
            follow_symlinks = (os.environ.get("DECKARD_FOLLOW_SYMLINKS", "0").strip().lower() in ("1", "true", "yes", "on"))
            p = Path(WorkspaceManager._normalize_path(path, follow_symlinks=follow_symlinks))
            for r in roots:
                root_path = Path(WorkspaceManager._normalize_path(r, follow_symlinks=follow_symlinks))
                if p == root_path or root_path in p.parents:
                    return True
            return False
        except Exception:
            return False

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
