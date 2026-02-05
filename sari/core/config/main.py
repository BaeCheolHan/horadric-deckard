import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from sari.core.workspace import WorkspaceManager
from sari.core.settings import settings
from .manager import ConfigManager

logger = logging.getLogger(__name__)


def _expanduser(p: str) -> str:
    return os.path.expanduser(p)


@dataclass(frozen=True)
class Config:
    workspace_root: str # Primary root
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
    store_content: bool
    gitignore_lines: list[str]
    http_api_host: str = "127.0.0.1"
    http_api_port: int = 47777
    exclude_content_bytes: int = 104857600
    engine_mode: str = "embedded"
    engine_auto_install: bool = True
    workspace_roots: list[str] = field(default_factory=list) # Optional for compatibility
    settings: Any = field(default=None, repr=False) # Access to centralized Settings object

    def __post_init__(self):
        # Ensure workspace_roots is always a list containing at least workspace_root
        if not self.workspace_roots:
            object.__setattr__(self, "workspace_roots", [self.workspace_root])
        elif self.workspace_root not in self.workspace_roots:
            # Sync workspace_root to be the first of roots
            object.__setattr__(self, "workspace_root", self.workspace_roots[0])

    @staticmethod
    def get_defaults(workspace_root: str) -> dict:
        """Central source for default configuration values."""
        return {
            "workspace_roots": [workspace_root],
            "workspace_root": workspace_root,
            "server_host": "127.0.0.1",
            "server_port": 47777,
            "http_api_host": "127.0.0.1",
            "http_api_port": 47777,
            "scan_interval_seconds": 180,
            "snippet_max_lines": 5,
            "max_file_bytes": 1000000, # Increased to 1MB
            "db_path": str(WorkspaceManager.get_global_db_path()),
            "include_ext": [".py", ".js", ".ts", ".java", ".kt", ".go", ".rs", ".md", ".json", ".yaml", ".yml", ".sh"],
            "include_files": ["pom.xml", "package.json", "Dockerfile", "Makefile", "build.gradle", "settings.gradle"],
            "exclude_dirs": [
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                "venv",
                "target",
                "build",
                "dist",
                "coverage",
                "vendor",
                "data",
            ],
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
                "*.db",
                "*.db-shm",
                "*.db-wal",
            ],
            "redact_enabled": True,
            "commit_batch_size": 500,
            "store_content": True,
            "gitignore_lines": [],
            "exclude_content_bytes": 104857600, # 100MB default for full content storage
            "engine_mode": "embedded",
            "engine_auto_install": True,
        }

    def save_paths_only(self, path: str, extra_paths: dict = None) -> None:
        """Persist resolved path-related configuration to disk (Write-back)."""
        extra_paths = extra_paths or {}
        data = {}
        # Load existing config to preserve non-path settings
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}

        data["roots"] = self.workspace_roots
        data["db_path"] = self.db_path
        # Optional path keys (if provided)
        for k, v in extra_paths.items():
            if v:
                data[k] = v
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Configuration saved to {path}")
        except Exception as e:
            logger.error(f"Failed to save configuration to {path}: {e}")

    @staticmethod
    def load(path: str, workspace_root_override: str = None, root_uri: str = None, settings_obj=None) -> "Config":
        settings_obj = settings_obj or settings
        raw = {}
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load config from {path}: {e}")

        # Backward compatibility
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

        # --- Multi-root Resolution ---
        config_roots = raw.get("roots") or raw.get("workspace_roots") or []
        if not config_roots and raw.get("workspace_root"):
            config_roots = [raw.get("workspace_root")]

        final_roots = WorkspaceManager.resolve_workspace_roots(
            root_uri=root_uri,
            config_roots=config_roots
        )
        if workspace_root_override:
            try:
                override_norm = WorkspaceManager._normalize_path(workspace_root_override, follow_symlinks=settings_obj.FOLLOW_SYMLINKS)
            except Exception:
                override_norm = workspace_root_override
            final_roots = [override_norm] + [r for r in final_roots if r != override_norm]

        if not final_roots:
             final_roots = [os.getcwd()]

        primary_root = final_roots[0]
        defaults = Config.get_defaults(primary_root)

        # Port and Engine Overrides via Settings
        server_port = int(raw.get("server_port", settings_obj.DAEMON_PORT))
        http_api_port = int(raw.get("http_api_port", settings_obj.HTTP_API_PORT))
        
        engine_mode = settings_obj.ENGINE_MODE or str(raw.get("engine_mode", defaults["engine_mode"])).strip().lower()
        if engine_mode not in ("embedded", "sqlite"):
            engine_mode = "embedded"

        engine_auto_install = settings_obj.ENGINE_AUTO_INSTALL if "SARI_ENGINE_AUTO_INSTALL" in os.environ else bool(raw.get("engine_auto_install", defaults["engine_auto_install"]))

        # DB path resolution
        db_path = settings_obj.CONFIG_PATH or raw.get("db_path")
        if not db_path:
            db_path = str(WorkspaceManager.get_global_db_path())

        # --- ConfigManager (Profiles + Add/Remove) ---
        manual_only = bool(raw.get("manual_only")) if "manual_only" in raw else settings_obj.MANUAL_ONLY
        cm = ConfigManager(primary_root, manual_only=manual_only, settings_obj=settings_obj)
        final_cfg = cm.resolve_final_config()
        include_ext = final_cfg.get("final_extensions", defaults["include_ext"])
        include_files = final_cfg.get("final_filenames", defaults["include_files"])
        exclude_dirs = final_cfg.get("final_exclude_dirs", defaults["exclude_dirs"])
        exclude_globs = final_cfg.get("final_exclude_globs", defaults["exclude_globs"])
        gitignore_lines = final_cfg.get("gitignore_lines", defaults["gitignore_lines"])

        # --- Construct Config Object ---
        cfg = Config(
            workspace_roots=final_roots,
            workspace_root=primary_root,
            server_host=raw.get("server_host", defaults["server_host"]),
            server_port=server_port,
            http_api_host=raw.get("http_api_host", defaults["http_api_host"]),
            http_api_port=http_api_port,
            scan_interval_seconds=int(raw.get("scan_interval_seconds", defaults["scan_interval_seconds"])),
            snippet_max_lines=int(raw.get("snippet_max_lines", defaults["snippet_max_lines"])),
            max_file_bytes=int(raw.get("max_file_bytes", defaults["max_file_bytes"])),
            db_path=_expanduser(str(db_path)),
            include_ext=list(include_ext),
            include_files=list(include_files),
            exclude_dirs=list(exclude_dirs),
            exclude_globs=list(exclude_globs),
            redact_enabled=bool(raw.get("redact_enabled", defaults["redact_enabled"])),
            commit_batch_size=int(raw.get("commit_batch_size", defaults["commit_batch_size"])),
            store_content=bool(raw.get("store_content", defaults["store_content"])),
            gitignore_lines=list(gitignore_lines),
            exclude_content_bytes=int(raw.get("exclude_content_bytes", defaults["exclude_content_bytes"])),
            engine_mode=engine_mode,
            engine_auto_install=engine_auto_install,
            settings=settings_obj,
        )

        if settings_obj.PERSIST_PATHS and path:
            cfg.save_paths_only(path)

        return cfg



def resolve_config_path(repo_root: str) -> str:
    """Resolve config path using unified WorkspaceManager logic."""
    return WorkspaceManager.resolve_config_path(repo_root)
