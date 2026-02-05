import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


try:
    from .workspace import WorkspaceManager  # type: ignore
except ImportError:
    from workspace import WorkspaceManager  # type: ignore

logger = logging.getLogger(__name__)


def _expanduser(p: str) -> str:
    return os.path.expanduser(p)

def _get_env_any(key_suffix: str, default: str = None) -> str:
    """Helper to check SARI_ prefix."""
    val = os.environ.get(f"SARI_{key_suffix}")
    if val is not None:
        return val
    return default


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
    http_api_host: str = "127.0.0.1"
    http_api_port: int = 47777
    exclude_content_bytes: int = 104857600
    engine_mode: str = "embedded"
    engine_auto_install: bool = True
    workspace_roots: list[str] = field(default_factory=list) # Optional for compatibility

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
            "db_path": str(WorkspaceManager.get_local_db_path(workspace_root)),
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
    def load(path: str, workspace_root_override: str = None, root_uri: str = None) -> "Config":
        raw = {}
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load config from {path}: {e}")

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

        # --- Multi-root Resolution ---
        # Sources for roots:
        # 1. workspace_root_override (argument) -> treated as a root
        # 2. Config file 'roots' or 'workspace_roots' (list)
        # 3. Config file 'workspace_root' (str) -> legacy
        config_roots = raw.get("roots") or raw.get("workspace_roots") or []
        if not config_roots and raw.get("workspace_root"):
            config_roots = [raw.get("workspace_root")]

        # Resolve base roots (env + config + legacy + optional root_uri).
        final_roots = WorkspaceManager.resolve_workspace_roots(
            root_uri=root_uri,
            config_roots=config_roots
        )
        if workspace_root_override:
            follow_symlinks = (os.environ.get("SARI_FOLLOW_SYMLINKS", "0").strip().lower() in ("1", "true", "yes", "on"))
            try:
                override_norm = WorkspaceManager._normalize_path(workspace_root_override, follow_symlinks=follow_symlinks)  # type: ignore
            except Exception:
                override_norm = workspace_root_override
            # Put override first, keep others after
            final_roots = [override_norm] + [r for r in final_roots if r != override_norm]

        if not final_roots:
             final_roots = [os.getcwd()]

        primary_root = final_roots[0]

        defaults = Config.get_defaults(primary_root)

        # Support port override (legacy)
        port_override = _get_env_any("PORT") or _get_env_any("PORT_OVERRIDE")
        server_port = int(port_override) if port_override else int(raw.get("server_port", defaults["server_port"]))

        # HTTP API port override (SSOT)
        http_port_override = _get_env_any("HTTP_API_PORT") or _get_env_any("HTTP_PORT")
        http_api_port = int(http_port_override) if http_port_override else int(raw.get("http_api_port", defaults["http_api_port"]))

        # Engine overrides (normalized into Config)
        env_engine_mode = (_get_env_any("ENGINE_MODE") or "").strip().lower()
        engine_mode = env_engine_mode or str(raw.get("engine_mode", defaults["engine_mode"])).strip().lower()
        if engine_mode not in ("embedded", "sqlite"):
            engine_mode = "embedded"

        env_auto_install = (_get_env_any("ENGINE_AUTO_INSTALL") or "").strip().lower()
        if env_auto_install in ("0", "false", "no", "off"):
            engine_auto_install = False
        elif env_auto_install in ("1", "true", "yes", "on"):
            engine_auto_install = True
        else:
            engine_auto_install = bool(raw.get("engine_auto_install", defaults["engine_auto_install"]))

        # Unified DB path resolution
        # Priority: Env > Config File > Default(primary_root)
        env_db_path = (_get_env_any("DB_PATH") or "").strip()

        db_path = ""
        if env_db_path:
            expanded = _expanduser(env_db_path)
            if os.path.isabs(expanded):
                db_path = expanded
            else:
                logger.warning(f"Ignoring relative DB_PATH '{env_db_path}'. Absolute path required.")

        if not db_path:
            raw_db_path = raw.get("db_path", "")
            # Check if packaged config logic applies (skip relative path check for packaged default?)
            # Simplified: just expand and use if absolute
            if raw_db_path:
                 expanded = _expanduser(raw_db_path)
                 if os.path.isabs(expanded):
                     db_path = expanded

        if not db_path:
            db_path = str(WorkspaceManager.get_local_db_path(primary_root))

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
            db_path=_expanduser(db_path),
            include_ext=list(raw.get("include_ext", defaults["include_ext"])),
            include_files=list(raw.get("include_files", defaults["include_files"])),
            exclude_dirs=list(raw.get("exclude_dirs", defaults["exclude_dirs"])),
            exclude_globs=list(raw.get("exclude_globs", defaults["exclude_globs"])),
            redact_enabled=bool(raw.get("redact_enabled", defaults["redact_enabled"])),
            commit_batch_size=int(raw.get("commit_batch_size", defaults["commit_batch_size"])),
            exclude_content_bytes=int(raw.get("exclude_content_bytes", defaults["exclude_content_bytes"])),
            engine_mode=engine_mode,
            engine_auto_install=engine_auto_install,
        )

        # --- Write-back (Persist) Logic ---
        persist_flag = (_get_env_any("PERSIST_ROOTS") or _get_env_any("PERSIST_PATHS") or "0").strip().lower()
        should_persist = persist_flag in ("1", "true", "yes", "on")

        if should_persist and path:
            extra = {
                "install_dir": (_get_env_any("INSTALL_DIR") or "").strip(),
                "data_dir": (_get_env_any("DATA_DIR") or "").strip(),
                "db_path": (_get_env_any("DB_PATH") or "").strip(),
                "config_path": (_get_env_any("CONFIG") or "").strip(),
            }
            cfg.save_paths_only(path, extra_paths=extra)

        return cfg



def resolve_config_path(repo_root: str) -> str:
    """Resolve config path using unified WorkspaceManager logic."""
    return WorkspaceManager.resolve_config_path(repo_root)
