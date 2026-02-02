import pytest
import shutil
import subprocess
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add project root
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound1EdgeCases:
    """Round 1: Handling Failures & Edge Cases"""

    def test_tc1_git_clone_failure(self, mock_env):
        """TC1: Network/Git failure during global install should abort gracefully."""
        args = type('Args', (), {"update": True, "yes": True, "quiet": False, "verbose": False})()
        
        with patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
            with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git clone")) as mock_run:
                with pytest.raises(SystemExit) as exc:
                    install.do_install(args)
                assert exc.value.code == 1
        
        assert not mock_env["install_dir"].exists(), "Install dir should not exist after failed clone"

    def test_tc2_readonly_install_dir(self, mock_env):
        """TC2: Install to read-only directory (parent) should fail/exit."""
        mock_env["install_dir"].parent.mkdir(parents=True, exist_ok=True)
        # Create dir
        mock_env["install_dir"].mkdir()
        
        # Make PARENT read-only to prevent rmtree of child
        parent = mock_env["install_dir"].parent
        parent.chmod(0o555)
        
        # Try to update (which tries to remove it)
        args = type('Args', (), {"update": True, "yes": True, "quiet": True})()
        
        with patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
            try:
                # Expect failure due to permission error on removing dir
                with pytest.raises(SystemExit):
                    install.do_install(args)
            finally:
                parent.chmod(0o777) # Restore permission
        
        # Cleanup
        if mock_env["install_dir"].exists():
             mock_env["install_dir"].chmod(0o777)

    def test_tc3_corrupted_config_file(self, mock_env, run_install):
        """TC3: Installing into a workspace with corrupted config.toml."""
        corrupt_cfg = mock_env["ws1"] / ".codex" / "config.toml"
        corrupt_cfg.write_text("INVALID TOML CONTENT [[[")
        
        # Should not crash, just append or fail gracefully? 
        # _upsert_mcp_config uses simple string parsing, so it handles garbage robustly.
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        content = corrupt_cfg.read_text()
        assert "[mcp_servers.deckard]" in content
        assert "INVALID TOML CONTENT" in content # Should preserve original garbage

    def test_tc4_missing_bootstrap_recovery(self, mock_env, run_install):
        """TC4: Install dir exists but is empty (missing bootstrap). Should fail or ask update."""
        mock_env["install_dir"].mkdir(parents=True, exist_ok=True)
        # No bootstrap.sh
        
        args = type('Args', (), {"update": False, "yes": True})()
        with patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             with pytest.raises(SystemExit):
                 install.do_install(args)

    def test_tc5_uninstall_when_not_installed(self, mock_env):
        """TC5: Uninstalling when directory doesn't exist should be a no-op."""
        assert not mock_env["install_dir"].exists()
        
        args = type('Args', (), {"uninstall": True, "yes": True, "quiet": True})()
        install.do_uninstall(args) # Should not raise
        
        assert not mock_env["install_dir"].exists()
