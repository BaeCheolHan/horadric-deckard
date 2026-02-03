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
        1. config.roots
        2. DECKARD_ROOTS_JSON
        3. DECKARD_ROOT_1..N
        4. DECKARD_WORKSPACE_ROOT (legacy)
        5. LOCAL_SEARCH_WORKSPACE_ROOT (legacy)
        6. root_uri (MCP initialize param, ephemeral)
        7. Fallback to cwd (only if no candidates)
        
        Returns:
            List of absolute, normalized paths.
        """
        candidates: list[tuple[str, str]] = []
        env_vars = roots_env if roots_env is not None else os.environ
        follow_symlinks = (env_vars.get("DECKARD_FOLLOW_SYMLINKS", "0").strip().lower() in ("1", "true", "yes", "on"))
        keep_nested = (env_vars.get("DECKARD_KEEP_NESTED_ROOTS", "0").strip().lower() in ("1", "true", "yes", "on"))

        # 1. config.roots
        if config_roots:
            for x in config_roots:
                if x:
                    candidates.append((str(x), "config"))

        # 2. DECKARD_ROOTS_JSON
        import json
        json_str = roots_json or env_vars.get("DECKARD_ROOTS_JSON", "")
        if json_str:
            try:
                loaded = json.loads(json_str)
                if isinstance(loaded, list):
                    for x in loaded:
                        if x:
                            candidates.append((str(x), "env"))
            except Exception:
                pass
                
        # 3. DECKARD_ROOT_1..N
        for k, v in env_vars.items():
            if k.startswith("DECKARD_ROOT_") and k[13:].isdigit():
                if v and v.strip():
                    candidates.append((v.strip(), "env"))
                    
        # 4. Legacy DECKARD_WORKSPACE_ROOT (Higher priority than LOCAL_SEARCH)
        legacy_val = (env_vars.get("DECKARD_WORKSPACE_ROOT") or "").strip()
        if legacy_val:
            if legacy_val == "${cwd}":
                candidates.append((os.getcwd(), "env"))
            else:
                candidates.append((legacy_val, "env"))

        # 5. Legacy LOCAL_SEARCH_WORKSPACE_ROOT
        ls_val = (env_vars.get("LOCAL_SEARCH_WORKSPACE_ROOT") or "").strip()
        if ls_val:
            if ls_val == "${cwd}":
                candidates.append((os.getcwd(), "env"))
            else:
                candidates.append((ls_val, "env"))
        
        # 6. root_uri (ephemeral)
        if root_uri:
            uri_path = root_uri[7:] if root_uri.startswith("file://") else root_uri
            try:
                if uri_path:
                    candidate = os.path.expanduser(uri_path)
                    if os.path.exists(candidate):
                        candidates.append((candidate, "root_uri"))
            except Exception:
                pass
        
        # 7. Fallback to cwd
        if not candidates:
            candidates.append((os.getcwd(), "fallback"))
            
        # Normalization
        resolved_paths: list[tuple[str, str]] = []
        seen = set()
        for p, src in candidates:
            try:
                abs_path = WorkspaceManager._normalize_path(p, follow_symlinks=follow_symlinks)
                if abs_path not in seen:
                    resolved_paths.append((abs_path, src))
                    seen.add(abs_path)
            except Exception:
                continue
                
        # Inclusion check while preserving priority order (first seen wins)
        final_roots: list[str] = []
        final_meta: list[tuple[str, str]] = []
        if keep_nested:
            for p, src in resolved_paths:
                final_roots.append(p)
                final_meta.append((p, src))
        else:
            for p, src in resolved_paths:
                p_path = Path(p)
                is_covered = False
                for existing, ex_src in final_meta:
                    try:
                        existing_path = Path(existing)
                        # If root_uri is a child of config/env, drop root_uri
                        if src == "root_uri" and ex_src in {"config", "env"}:
                            if p_path == existing_path or existing_path in p_path.parents or p.startswith(existing + os.sep):
                                is_covered = True
                                break
                        # If root_uri is parent of config/env, keep both (skip collapse)
                        if ex_src == "root_uri" and src in {"config", "env"}:
                            if p_path == existing_path or p.startswith(existing + os.sep) or existing_path in p_path.parents:
                                is_covered = False
                                continue
                        # Default: collapse nested roots (parent keeps, child removed)
                        if p_path == existing_path or existing_path in p_path.parents or p.startswith(existing + os.sep):
                            is_covered = True
                            break
                    except Exception:
                        continue
                if not is_covered:
                    final_meta.append((p, src))
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
        1. DECKARD_CONFIG environment variable (SSOT)
        2. Default SSOT path (~/.config/deckard/config.json or %APPDATA%/deckard/config.json)
        """
        val = (os.environ.get("DECKARD_CONFIG") or "").strip()
        if val:
            p = Path(os.path.expanduser(val))
            return str(p.resolve())

        if os.name == "nt":
            ssot = Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))) / "deckard" / "config.json"
        else:
            ssot = Path.home() / ".config" / "deckard" / "config.json"

        if ssot.exists():
            return str(ssot.resolve())

        # Legacy migration (one-time copy + backup)
        legacy_candidates = [
            Path(workspace_root) / ".codex" / "tools" / "deckard" / "config" / "config.json",
        ]
        legacy_home = Path.home() / ".deckard" / "config.json"
        legacy_candidates.append(legacy_home)
        for legacy in legacy_candidates:
            if legacy.exists():
                try:
                    ssot.parent.mkdir(parents=True, exist_ok=True)
                    ssot.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
                    bak = legacy.with_suffix(legacy.suffix + ".bak")
                    try:
                        legacy.rename(bak)
                    except Exception:
                        marker = legacy.parent / ".migrated"
                        marker.write_text(f"migrated to {ssot}", encoding="utf-8")
                    print(f"[deckard] migrated legacy config from {legacy} to {ssot}")
                except Exception:
                    pass
                break

        return str(ssot.resolve())
    
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
