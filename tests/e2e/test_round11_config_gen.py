import pytest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound11ConfigGen:
    """Round 11: Detailed TOML Config Generation logic"""

    def test_tc1_toml_path_escaping(self, mock_env):
        """TC1: Windows-style backslashes in paths should be escaped in TOML."""
        # Force a path with backslashes using raw string
        weird_ws = r"C:\Users\Deckard\Workspace"
        
        args = type('Args', (), {"update": False, "yes": True, "quiet": True})()
        
        # Ensure INSTALL_DIR and bootstrap exist so global install is skipped
        mock_env["install_dir"].mkdir(parents=True, exist_ok=True)
        (mock_env["install_dir"] / "bootstrap.sh").touch()

        # Define side_effect for exists() to return True for install_dir/bootstrap, False for config
        original_exists = Path.exists
        def exists_side_effect(self):
            if str(self) == str(mock_env["install_dir"]) or str(self) == str(mock_env["install_dir"] / "bootstrap.sh"):
                return True
            if ".codex" in str(self) or ".gemini" in str(self):
                return False # Configs don't exist yet
            return original_exists(self)

        with patch("install._resolve_workspace_root", return_value=weird_ws), \
             patch("install._terminate_pids"), \
             patch("install._list_deckard_pids", return_value=[]), \
             patch("pathlib.Path.exists", side_effect=exists_side_effect, autospec=True), \
             patch("pathlib.Path.write_text") as mock_write:
             
             install.do_install(args)
             
             # Check what was written
             found = False
             for call in mock_write.call_args_list:
                 content = call[0][0] # first arg
                 if "mcp_servers.deckard" in content:
                     # Check for escaped path
                     if r"C:\Users\Deckard\Workspace" in content or "C:\\Users\\Deckard\\Workspace" in content:
                         found = True
             assert found, "Config content did not contain escaped windows path"


    def test_tc2_config_append_behavior(self, mock_env, run_install):
        """TC2: Install should APPEND to existing config, not overwrite."""
        cfg = mock_env["ws1"] / ".codex" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("existing_key = 'value'\n")
        
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        content = cfg.read_text()
        assert "existing_key = 'value'" in content
        assert "[mcp_servers.deckard]" in content

    def test_tc3_config_idempotency_check(self, mock_env, run_install):
        """TC3: Repeated installs should not create duplicate [mcp_servers.deckard] blocks."""
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        content = (mock_env["ws1"] / ".codex" / "config.toml").read_text()
        assert content.count("[mcp_servers.deckard]") == 1

    def test_tc4_env_injection_format(self, mock_env, run_install):
        """TC4: Environment variables block format check."""
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        content = (mock_env["ws1"] / ".codex" / "config.toml").read_text()
        # Should look like: env = { DECKARD_WORKSPACE_ROOT = "..." }
        assert "env = {" in content
        assert "DECKARD_WORKSPACE_ROOT =" in content

    def test_tc5_startup_timeout_config(self, mock_env, run_install):
        """TC5: Ensure startup_timeout_sec is set (critical for slow machines)."""
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        content = (mock_env["ws1"] / ".codex" / "config.toml").read_text()
        assert "startup_timeout_sec = 60" in content
