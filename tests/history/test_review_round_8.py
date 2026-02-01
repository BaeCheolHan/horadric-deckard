
import pytest
import os
from pathlib import Path
from unittest.mock import patch
from app.workspace import WorkspaceManager

class TestReviewRound8:
    """Round 8: Workspace Manager Resolution Logic."""

    def test_resolve_root_uri(self, tmp_path):
        """Test 1: root_uri takes precedence."""
        uri = f"file://{tmp_path}"
        # It must exist
        path = WorkspaceManager.resolve_workspace_root(uri)
        assert path == str(tmp_path.resolve())

        # Without file://
        path2 = WorkspaceManager.resolve_workspace_root(str(tmp_path))
        assert path2 == str(tmp_path.resolve())

    def test_env_var_override(self, tmp_path):
        """Test 2: Environment variable DECKARD_WORKSPACE_ROOT overrides fallback."""
        with patch.dict(os.environ, {"DECKARD_WORKSPACE_ROOT": str(tmp_path)}):
            # No root_uri passed
            res = WorkspaceManager.resolve_workspace_root(None)
            assert res == str(tmp_path.resolve())

    def test_codex_root_marker(self, tmp_path):
        """Test 3: Find .codex-root in parent directory."""
        # Structure: tmp/parent/.codex-root, tmp/parent/child/
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / ".codex-root").touch()
        child = parent / "child"
        child.mkdir()
        
        # We need to change cwd to child
        prev_cwd = os.getcwd()
        try:
            os.chdir(str(child))
            # Resolve with no args, no env
            with patch.dict(os.environ, {}, clear=True):
                 res = WorkspaceManager.resolve_workspace_root(None)
                 assert res == str(parent.resolve())
        finally:
            os.chdir(prev_cwd)

    def test_config_path_precedence(self, tmp_path):
        """Test 4: Config path precedence."""
        # 1. Env
        with patch.dict(os.environ, {"DECKARD_CONFIG": str(tmp_path / "env.json")}):
            (tmp_path / "env.json").touch()
            res = WorkspaceManager.resolve_config_path("/nowhere")
            assert res == str((tmp_path / "env.json").resolve())

        # 2. Workspace
        ws = tmp_path / "ws"
        cfg_dir = ws / ".codex/tools/deckard/config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").touch()
        
        with patch.dict(os.environ, {}, clear=True):
            res = WorkspaceManager.resolve_config_path(str(ws))
            assert res == str((cfg_dir / "config.json").resolve())

    def test_helper_paths(self):
        """Test 5: Helper path matches expected structure."""
        p = WorkspaceManager.get_local_db_path("/foo/bar")
        assert p == Path("/foo/bar/.codex/tools/deckard/data/index.db")
