import os
import sys
import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional, List
from sari.core.settings import settings

class WorkspaceManager:
    """Manages workspace detection, explicit boundaries (.sariroot), and global paths."""
    settings = settings

    @staticmethod
    def set_settings(settings_obj):
        WorkspaceManager.settings = settings_obj

    @staticmethod
    def find_project_root(path: str) -> str:
        """Find the nearest directory containing .sariroot."""
        curr = Path(path).resolve()
        for parent in [curr] + list(curr.parents):
            if (parent / ".sariroot").exists():
                return str(parent)
        return str(curr)

    @staticmethod
    def _strip_trailing_sep(path: str) -> str:
        if not path:
            return path
        stripped = path.rstrip(os.sep)
        # Keep filesystem root stable ("/" on POSIX).
        if not stripped:
            return os.sep
        return stripped

    @staticmethod
    def normalize_path(p: str) -> str:
        """Standard normalization for all workspace paths in Sari. Fixes Mac symlink issues."""
        if not p:
            p = os.getcwd()
        try:
            # Mac specific: ensure /tmp -> /private/tmp resolution for FK stability
            resolved = str(Path(p).expanduser().resolve())
            return WorkspaceManager._strip_trailing_sep(resolved)
        except Exception:
            # Fallback to absolute if resolve fails
            res = os.path.abspath(os.path.expanduser(p))
            if os.name == "nt": res = res.lower()
            return WorkspaceManager._strip_trailing_sep(res)

    @staticmethod
    def root_id(path: str) -> str:
        """Stable root id derived from project root boundary."""
        project_root = WorkspaceManager.find_project_root(path)
        digest = hashlib.sha1(project_root.encode("utf-8")).hexdigest()[:8]
        return f"root-{digest}"

    @staticmethod
    def root_id_for_workspace(workspace_root: str) -> str:
        """Stable root id for an explicit workspace root (no parent auto-lift)."""
        normalized = WorkspaceManager.normalize_path(workspace_root)
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
        return f"root-{digest}"

    @staticmethod
    def _normalize_path(path: str, follow_symlinks: bool) -> str:
        expanded = os.path.expanduser(path)
        normalized = os.path.realpath(expanded) if follow_symlinks else os.path.abspath(expanded)
        if os.name == "nt": normalized = normalized.lower()
        return WorkspaceManager._strip_trailing_sep(normalized)

    @staticmethod
    def resolve_workspace_roots(root_uri: Optional[str] = None, config_roots: Optional[List[str]] = None) -> List[str]:
        roots = []
        if config_roots:
            for r in config_roots:
                if r: roots.append(WorkspaceManager.normalize_path(r))
        if root_uri:
            p = root_uri[7:] if root_uri.startswith("file://") else root_uri
            roots.append(WorkspaceManager.normalize_path(p))
        if WorkspaceManager.settings.WORKSPACE_ROOT:
            roots.append(WorkspaceManager.normalize_path(WorkspaceManager.settings.WORKSPACE_ROOT))
        return list(dict.fromkeys(roots)) or [WorkspaceManager.normalize_path(os.getcwd())]

    @staticmethod
    def resolve_workspace_root(root_uri: Optional[str] = None) -> str:
        """Resolve a single workspace root (primary)."""
        roots = WorkspaceManager.resolve_workspace_roots(root_uri=root_uri)
        root = roots[0] if roots else os.getcwd()
        return WorkspaceManager.normalize_path(root)

    @staticmethod
    def resolve_config_path(_repo_root: str) -> str:
        """
        Resolve config path.
        Priority:
        1) SARI_CONFIG (explicit override)
        2) workspace-local .sari/mcp-config.json (preferred)
        3) global ~/.config/sari/config.json (legacy fallback)
        """
        val = WorkspaceManager.settings.CONFIG_PATH
        if val:
            return str(Path(os.path.expanduser(val)).resolve())
        repo_root = _repo_root or os.getcwd()
        ws_root = WorkspaceManager.find_project_root(repo_root)
        preferred = WorkspaceManager.workspace_config_path(ws_root)
        WorkspaceManager._migrate_legacy_workspace_config(ws_root, preferred)
        if preferred.exists():
            return str(preferred)
        return str(Path(WorkspaceManager.settings.GLOBAL_CONFIG_DIR) / "config.json")

    @staticmethod
    def workspace_config_path(root_path: str) -> Path:
        """Preferred workspace-local config path."""
        root = Path(root_path)
        return root / WorkspaceManager.settings.WORKSPACE_CONFIG_DIR_NAME / "mcp-config.json"

    @staticmethod
    def legacy_workspace_config_path(root_path: str) -> Path:
        """Legacy workspace-local config path kept for backward compatibility."""
        root = Path(root_path)
        return root / WorkspaceManager.settings.WORKSPACE_CONFIG_DIR_NAME / "config.json"

    @staticmethod
    def _looks_like_sqlite(path: Path) -> bool:
        try:
            with path.open("rb") as f:
                head = f.read(16)
            return head.startswith(b"SQLite format 3")
        except Exception:
            return False

    @staticmethod
    def _migrate_legacy_workspace_config(root_path: str, preferred_path: Path) -> None:
        """
        One-way migration:
        - If legacy config.json is valid JSON and preferred file is absent, copy it.
        - Never migrate if legacy file looks like SQLite (corrupted/misused path).
        """
        legacy = WorkspaceManager.legacy_workspace_config_path(root_path)
        if preferred_path.exists() or not legacy.exists():
            return
        if WorkspaceManager._looks_like_sqlite(legacy):
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                preferred_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, preferred_path)
        except Exception:
            return

    @staticmethod
    def get_global_data_dir() -> Path:
        return Path.home() / ".local" / "share" / "sari"

    @staticmethod
    def get_global_db_path() -> Path:
        return WorkspaceManager.get_global_data_dir() / "index.db"

    @staticmethod
    def get_workspace_data_dir(root_path: str) -> Path:
        root = Path(WorkspaceManager.normalize_path(root_path))
        return root / WorkspaceManager.settings.WORKSPACE_CONFIG_DIR_NAME

    @staticmethod
    def get_workspace_db_path(root_path: str) -> Path:
        return WorkspaceManager.get_workspace_data_dir(root_path) / "index.db"

    @staticmethod
    def get_global_log_dir() -> Path:
        return Path.home() / "Library" / "Logs" / "sari" if sys.platform == "darwin" else WorkspaceManager.get_global_data_dir() / "logs"

    @staticmethod
    def get_engine_index_dir(policy: Optional[str] = None, roots: Optional[List[str]] = None, root_id: Optional[str] = None) -> Path:
        """
        Index directory selector.
        Policy:
        - global (default): single index
        - roots_hash: per-roots group index (legacy-friendly)
        - per_root: one index per root_id
        """
        policy = (policy or WorkspaceManager.settings.ENGINE_INDEX_POLICY or "global").lower()
        base = WorkspaceManager.get_global_data_dir() / "index"
        if policy in {"global", "single"}:
            return base / "global"
        if policy in {"roots_hash", "legacy"}:
            roots = roots or []
            seed = "::".join(sorted([WorkspaceManager._normalize_path(r, WorkspaceManager.settings.FOLLOW_SYMLINKS) for r in roots]))
            digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8] if seed else "default"
            return base / f"roots-{digest}"
        if policy in {"per_root", "shard"}:
            rid = root_id or (WorkspaceManager.root_id_for_workspace(roots[0]) if roots else "root-default")
            return base / f"{rid}"
        return base / "global"

    @staticmethod
    def ensure_sari_dir(root_path: str) -> None:
        root = Path(root_path)
        sari_dir = root / WorkspaceManager.settings.WORKSPACE_CONFIG_DIR_NAME
        sari_dir.mkdir(parents=True, exist_ok=True)
        gitignore = root / ".gitignore"
        entry = f"{WorkspaceManager.settings.WORKSPACE_CONFIG_DIR_NAME}/"
        try:
            if not gitignore.exists():
                gitignore.write_text(entry + "\n", encoding="utf-8")
                return
            text = gitignore.read_text(encoding="utf-8")
            if entry not in text:
                with gitignore.open("a", encoding="utf-8") as f:
                    if not text.endswith("\n"):
                        f.write("\n")
                    f.write(entry + "\n")
        except Exception:
            pass
