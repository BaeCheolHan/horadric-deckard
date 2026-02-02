import pytest
import os
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Setup Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound6Paths:
    """Round 6: Path Handling & Environment Edge Cases"""

    def test_tc1_install_path_with_spaces(self, mock_env, run_install):
        """TC1: Install directory path contains spaces."""
        # Update mock_env to use path with spaces
        spaced_dir = mock_env["home"] / "Application Support" / "Deckard"
        install.INSTALL_DIR = spaced_dir
        
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert spaced_dir.exists()
        assert (spaced_dir / "bootstrap.sh").exists()

    def test_tc2_workspace_path_unicode(self, mock_env, run_install):
        """TC2: Workspace path contains Unicode (Korean)."""
        korean_ws = mock_env["home"] / "한글_작업공간"
        korean_ws.mkdir()
        (korean_ws / ".codex").mkdir()
        
        run_install({"update": False, "yes": True}, cwd=korean_ws)
        
        cfg = korean_ws / ".codex" / "config.toml"
        assert cfg.exists()
        # Verify path in content is correctly encoded
        assert "한글_작업공간" in cfg.read_text(encoding="utf-8")

    def test_tc3_symlinked_install_dir(self, mock_env, run_install):
        """TC3: INSTALL_DIR is a symlink to another location."""
        real_dir = mock_env["home"] / "real_deckard"
        link_dir = mock_env["home"] / "link_deckard"
        
        # Pre-create real dir
        real_dir.mkdir()
        os.symlink(real_dir, link_dir)
        
        install.INSTALL_DIR = link_dir
        
        # Install should follow link or replace it? 
        # Standard behavior: rmtree removes link if exists? 
        # If it's a first install (update=False), it might error if exists.
        # Let's try update=True which triggers removal logic.
        
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        # rmtree on a symlink usually removes the link, not target content.
        # Then git clone creates a new directory at link_dir.
        assert link_dir.exists()
        assert not link_dir.is_symlink() # Should be replaced by real dir
        assert (link_dir / "bootstrap.sh").exists()

    def test_tc4_relative_path_resolution(self, mock_env):
        """TC4: --workspace-root passed as relative path should resolve to absolute."""
        # This tests internal _resolve_workspace_root logic implicitly via install flow
        # But we mock _resolve... in run_install.
        # So we test the function directly.
        os.chdir(mock_env["home"])
        rel_ws = "projects/my_ws"
        (mock_env["home"] / "projects" / "my_ws").mkdir(parents=True)
        
        # Set env var as relative path
        with patch.dict("os.environ", {"DECKARD_WORKSPACE_ROOT": rel_ws}):
            resolved = install._resolve_workspace_root()
            assert Path(resolved).is_absolute()
            assert str(mock_env["home"]) in resolved

    def test_tc5_home_is_root(self, mock_env, run_install):
        """TC5: Extreme edge case where HOME is / (simulating container/root)."""
        # We can't actually change HOME to / safely in test without risk,
        # but we can simulate the path construction logic.
        # install.INSTALL_DIR is already patched.
        # We just verify it works if INSTALL_DIR is e.g. /opt/deckard
        
        opt_dir = Path(mock_env["home"]) / "opt" / "deckard"
        install.INSTALL_DIR = opt_dir
        
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        assert opt_dir.exists()
