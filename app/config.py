import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path


try:
    from .workspace import WorkspaceManager  # type: ignore
except ImportError:
    from workspace import WorkspaceManager  # type: ignore

logger = logging.getLogger(__name__)


def _expanduser(p: str) -> str:
    return os.path.expanduser(p)


@dataclass(frozen=True)
class Config:
    workspace_root: str
    server_host: str
    server_port: int
    scan_interval_seconds: int
    snippet_max_lines: int
    max_file_bytes: int
    db_path: str
    include_ext: list[str]
    include_files: list[str]
    exclude_dirs: list[str]
    exclude_globs: list[str]
    redact_enabled: bool
    commit_batch_size: int

    @staticmethod
    def load(path: str, workspace_root_override: str = None) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Backward compatibility: legacy "indexing" schema
        legacy_indexing = raw.get("indexing", {}) if isinstance(raw, dict) else {}
        if "include_ext" not in raw and "include_extensions" in legacy_indexing:
            raw = dict(raw)
            raw["include_ext"] = legacy_indexing.get("include_extensions", [])
        if "exclude_dirs" not in raw and "exclude_patterns" in legacy_indexing:
            raw = dict(raw)
            legacy_excludes = list(legacy_indexing.get("exclude_patterns", []))
            raw["exclude_dirs"] = legacy_excludes
            if "exclude_globs" not in raw:
                raw["exclude_globs"] = [p for p in legacy_excludes if any(c in p for c in ["*", "?"])]

        # Portability: allow runtime overrides for workspace root.
        # This helps when the packaged config is used in different locations.
        # DECKARD_* preferred, LOCAL_SEARCH_* for backward compatibility
        env_workspace_root = os.environ.get("DECKARD_WORKSPACE_ROOT") or os.environ.get("LOCAL_SEARCH_WORKSPACE_ROOT")
        if workspace_root_override:
            raw = dict(raw)
            raw["workspace_root"] = workspace_root_override
        elif env_workspace_root:
            raw = dict(raw)
            raw["workspace_root"] = env_workspace_root
        # Support port override for automatic port selection on conflict
        port_override = os.environ.get("DECKARD_PORT") or os.environ.get("LOCAL_SEARCH_PORT_OVERRIDE")
        if port_override:
            server_port = int(port_override)
        else:
            server_port = int(raw.get("server_port", 47777))

        # v2.5.0: Force workspace-local DB path to prevent cross-repo pollution.
        workspace_root = _expanduser(raw["workspace_root"])
        
        # v2.5.3: Unified DB path resolution
        # Priority: ENV DECKARD_DB_PATH -> ENV LOCAL_SEARCH_DB_PATH -> config.json (if abs) -> workspace-local
        # SECURITY: Refuse relative paths for DB_PATH to prevent unintended file creation.
        env_db_path = (os.environ.get("DECKARD_DB_PATH") or os.environ.get("LOCAL_SEARCH_DB_PATH") or "").strip()
        
        db_path = ""
        if env_db_path:
            expanded = _expanduser(env_db_path)
            if os.path.isabs(expanded):
                db_path = expanded
            else:
                logger.warning(f"Ignoring relative DB_PATH '{env_db_path}'. Absolute path required.")
        
        if not db_path:
            raw_db_path = raw.get("db_path", "")
            if raw_db_path:
                expanded = _expanduser(raw_db_path)
                if os.path.isabs(expanded):
                    db_path = expanded
                else:
                    logger.warning(f"Ignoring relative db_path in config '{raw_db_path}'. Absolute path required.")
        
        if not db_path:
            db_path = os.path.join(workspace_root, ".codex", "tools", "deckard", "data", "index.db")

        return Config(
            workspace_root=workspace_root,
            server_host=raw.get("server_host", "127.0.0.1"),
            server_port=server_port,
            scan_interval_seconds=int(raw.get("scan_interval_seconds", 180)),
            snippet_max_lines=int(raw.get("snippet_max_lines", 5)),
            max_file_bytes=int(raw.get("max_file_bytes", 800000)),
            db_path=_expanduser(db_path),
            include_ext=list(raw.get("include_ext", [])),
            include_files=list(raw.get("include_files", [])),
            exclude_dirs=list(raw.get("exclude_dirs", [])),
            exclude_globs=list(raw.get("exclude_globs", [])),
            redact_enabled=bool(raw.get("redact_enabled", True)),
            commit_batch_size=int(raw.get("commit_batch_size", 500)),
        )


def resolve_config_path(repo_root: str) -> str:
    """Resolve config path using unified WorkspaceManager logic."""
    return WorkspaceManager.resolve_config_path(repo_root)
