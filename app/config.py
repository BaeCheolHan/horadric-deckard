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
    exclude_content_bytes: int = 104857600 # v2.7.0 (Default: 100MB)

    @staticmethod
    def get_defaults(workspace_root: str) -> dict:
        """Central source for default configuration values (v2.7.0)."""
        return {
            "workspace_root": workspace_root,
            "server_host": "127.0.0.1",
            "server_port": 47777,
            "scan_interval_seconds": 180,
            "snippet_max_lines": 5,
            "max_file_bytes": 1000000, # Increased to 1MB
            "db_path": str(WorkspaceManager.get_local_db_path(workspace_root)),
            "include_ext": [".py", ".js", ".ts", ".java", ".kt", ".go", ".rs", ".md", ".json", ".yaml", ".yml", ".sh"],
            "include_files": ["pom.xml", "package.json", "Dockerfile", "Makefile", "build.gradle", "settings.gradle"],
            "exclude_dirs": [".git", "node_modules", "__pycache__", ".venv", "venv", "target", "build", "dist", "coverage", "vendor"],
            "exclude_globs": [
                "*.min.js",
                "*.min.css",
                "*.map",
                "*.lock",
                "package-lock.json",
                "yarn.lock",
                "pnpm-lock.yaml",
                "*.class",
                "*.pyc",
                "*.pyo",
                "__pycache__/*",
            ],
            "redact_enabled": True,
            "commit_batch_size": 500,
            "exclude_content_bytes": 104857600, # 100MB default for full content storage
        }

    @staticmethod
    def load(path: str, workspace_root_override: str = None) -> "Config":
        raw = {}
        if path and os.path.exists(path):
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
        env_workspace_root = os.environ.get("DECKARD_WORKSPACE_ROOT") or os.environ.get("LOCAL_SEARCH_WORKSPACE_ROOT")
        workspace_root = workspace_root_override or env_workspace_root or raw.get("workspace_root") or os.getcwd()
        workspace_root = _expanduser(workspace_root)
        
        defaults = Config.get_defaults(workspace_root)

        # Support port override
        port_override = os.environ.get("DECKARD_PORT") or os.environ.get("LOCAL_SEARCH_PORT_OVERRIDE")
        server_port = int(port_override) if port_override else int(raw.get("server_port", defaults["server_port"]))

        # Unified DB path resolution
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
            package_root = Path(__file__).resolve().parents[1]
            packaged_config = str(package_root / "config" / "config.json")
            is_packaged_config = path and str(Path(path).resolve()) == packaged_config
            if raw_db_path and not is_packaged_config:
                expanded = _expanduser(raw_db_path)
                if os.path.isabs(expanded):
                    db_path = expanded
                else:
                    logger.warning(f"Ignoring relative db_path in config '{raw_db_path}'. Absolute path required.")
        
        if not db_path:
            db_path = defaults["db_path"]

        return Config(
            workspace_root=workspace_root,
            server_host=raw.get("server_host", defaults["server_host"]),
            server_port=server_port,
            scan_interval_seconds=int(raw.get("scan_interval_seconds", defaults["scan_interval_seconds"])),
            snippet_max_lines=int(raw.get("snippet_max_lines", defaults["snippet_max_lines"])),
            max_file_bytes=int(raw.get("max_file_bytes", defaults["max_file_bytes"])),
            db_path=_expanduser(db_path),
            include_ext=list(raw.get("include_ext", defaults["include_ext"])),
            include_files=list(raw.get("include_files", defaults["include_files"])),
            exclude_dirs=list(raw.get("exclude_dirs", defaults["exclude_dirs"])),
            exclude_globs=list(raw.get("exclude_globs", defaults["exclude_globs"])),
            redact_enabled=bool(raw.get("redact_enabled", defaults["redact_enabled"])),
            commit_batch_size=int(raw.get("commit_batch_size", defaults["commit_batch_size"])),
            exclude_content_bytes=int(raw.get("exclude_content_bytes", defaults["exclude_content_bytes"])),
        )



def resolve_config_path(repo_root: str) -> str:
    """Resolve config path using unified WorkspaceManager logic."""
    return WorkspaceManager.resolve_config_path(repo_root)
