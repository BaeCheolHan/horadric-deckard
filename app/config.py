import json
import os
from dataclasses import dataclass
from pathlib import Path


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

        # Portability: allow runtime overrides for workspace root.
        # This helps when the packaged config is used in different locations.
        env_workspace_root = os.environ.get("LOCAL_SEARCH_WORKSPACE_ROOT")
        if workspace_root_override:
            raw = dict(raw)
            raw["workspace_root"] = workspace_root_override
        elif env_workspace_root:
            raw = dict(raw)
            raw["workspace_root"] = env_workspace_root
        # Support port override for automatic port selection on conflict
        port_override = os.environ.get("LOCAL_SEARCH_PORT_OVERRIDE")
        if port_override:
            server_port = int(port_override)
        else:
            server_port = int(raw.get("server_port", 47777))

        # v2.5.0: Force workspace-local DB path to prevent cross-repo pollution.
        # We no longer support ~/.cache/deckard/ defaults.
        workspace_root = _expanduser(raw["workspace_root"])
        default_db_path = os.path.join(workspace_root, ".codex", "tools", "deckard", "data", "index.db")

        # Allow override from config.json ONLY if it is an absolute path (debugging),
        # otherwise fallback to workspace-local.
        raw_db_path = raw.get("db_path", "")
        if raw_db_path and os.path.isabs(_expanduser(raw_db_path)):
            db_path = _expanduser(raw_db_path)
        else:
            db_path = default_db_path

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
    """Resolve config path. Override with env LOCAL_SEARCH_CONFIG."""
    override = os.environ.get("LOCAL_SEARCH_CONFIG")
    if override:
        return override
    return str(Path(repo_root) / ".codex" / "tools" / "deckard" / "config" / "config.json")
