import pytest
import shutil
from unittest.mock import patch
import sys
from pathlib import Path

# Add project root
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound2Logic:
    """Round 2: Install Logic & Config Manipulation"""

    def test_tc1_idempotent_install(self, mock_env, run_install):
        """TC1: Installing twice in same workspace should update config, not error."""
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        mtime1 = (mock_env["ws1"] / ".codex" / "config.toml").stat().st_mtime
        
        # Run again
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        mtime2 = (mock_env["ws1"] / ".codex" / "config.toml").stat().st_mtime
        
        # Content should be valid (single block)
        content = (mock_env["ws1"] / ".codex" / "config.toml").read_text()
        assert content.count("[mcp_servers.deckard]") == 1

    def test_tc2_cross_platform_config(self, mock_env, run_install):
        """TC2: Ensure both Codex and Gemini configs are updated."""
        # ws1 has both folders created in conftest
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert (mock_env["ws1"] / ".codex" / "config.toml").exists()
        assert (mock_env["ws1"] / ".gemini" / "config.toml").exists()

    def test_tc3_global_config_purge(self, mock_env, run_install):
        """TC3: Global configs in HOME should be cleaned up."""
        global_codex = mock_env["home"] / ".codex" / "config.toml"
        global_codex.parent.mkdir(parents=True)
        global_codex.write_text("[mcp_servers.deckard]\ncommand='old'")
        
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert "[mcp_servers.deckard]" not in global_codex.read_text()

    def test_tc4_update_flag_replaces_files(self, mock_env, run_install):
        """TC4: --update flag should trigger git clone and replace files."""
        # 1. Fake existing install
        mock_env["install_dir"].mkdir(parents=True)
        (mock_env["install_dir"] / "bootstrap.sh").write_text("OLD")
        
        # 2. Update
        mock_run = run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        # 3. Check git clone call
        called_clone = False
        for call in mock_run.call_args_list:
            if "clone" in call[0][0]:
                called_clone = True
        assert called_clone
        
        # 4. Check file replaced (by mock clone logic)
        assert "v1.0.0" in (mock_env["install_dir"] / "bootstrap.sh").read_text()

    def test_tc5_workspace_isolation(self, mock_env, run_install):
        """TC5: Installing in WS1 should NOT affect WS2 configs."""
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert (mock_env["ws1"] / ".codex" / "config.toml").exists()
        assert not (mock_env["ws2"] / ".codex" / "config.toml").exists()
