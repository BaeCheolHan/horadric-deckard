import pytest
from unittest.mock import patch
import sys
from pathlib import Path
import os

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound10Integration:
    """Round 10: Advanced Integration & Recovery"""

    def test_tc1_install_recovery_loop(self, mock_env, run_install):
        """TC1: Install -> Fail -> Update (Recovery)."""
        # 1. Install failure simulation (partial install)
        mock_env["install_dir"].mkdir(parents=True)
        # bootstrap missing
        
        # 2. Configure attempt (fails because missing bootstrap)
        with pytest.raises(SystemExit):
            run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
            
        # 3. Recovery via Update
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        assert (mock_env["install_dir"] / "bootstrap.sh").exists()

    def test_tc2_multi_workspace_concurrent_config(self, mock_env, run_install):
        """TC2: Configure WS1 then WS2 sequentially (simulate user workflow)."""
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        # WS1 active
        assert (mock_env["ws1"] / ".codex" / "config.toml").exists()
        
        # Switch to WS2
        run_install({"update": False, "yes": True}, cwd=mock_env["ws2"])
        
        # WS2 active
        assert (mock_env["ws2"] / ".codex" / "config.toml").exists()
        
        # WS1 config remains untouched
        assert (mock_env["ws1"] / ".codex" / "config.toml").exists()

    def test_tc3_uninstall_removes_all_traces(self, mock_env):
        """TC3: Uninstall cleans global configs and current workspace."""
        # Setup Global Config (Legacy)
        global_cfg = mock_env["home"] / ".codex" / "config.toml"
        global_cfg.parent.mkdir(parents=True)
        global_cfg.write_text("[mcp_servers.deckard]\ncmd=1")
        
        mock_env["install_dir"].mkdir(parents=True)
        
        args = type('Args', (), {"uninstall": True, "yes": True})()
        
        # Patch everything needed for uninstall
        with patch("install._list_deckard_pids", return_value=[]), \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             
             old_cwd = os.getcwd()
             os.chdir(mock_env["ws1"])
             try:
                 install.do_uninstall(args)
             finally:
                 os.chdir(old_cwd)
                 
        assert not mock_env["install_dir"].exists()
        assert "[mcp_servers.deckard]" not in global_cfg.read_text()

    def test_tc4_manual_bootstrap_check(self, mock_env, run_install):
        """TC4: User manually deleted bootstrap.sh, install should detect and fail."""
        mock_env["install_dir"].mkdir(parents=True)
        (mock_env["install_dir"] / "other_file").touch()
        
        with pytest.raises(SystemExit) as exc:
            run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert exc.value.code == 1

    def test_tc5_full_reinstall_clean(self, mock_env, run_install):
        """TC5: Install -> Uninstall -> Install (Clean Slate)."""
        # 1. Install
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        # 2. Uninstall
        args = type('Args', (), {"uninstall": True, "yes": True})()
        with patch("install._list_deckard_pids", return_value=[]), \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             os.chdir(mock_env["ws1"])
             install.do_uninstall(args)
             
        # 3. Re-Install
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert (mock_env["install_dir"] / "bootstrap.sh").exists()
