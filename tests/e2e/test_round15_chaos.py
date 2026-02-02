import pytest
import shutil
import os
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound15Chaos:
    """Round 15: Chaos & Recovery Integration"""

    def test_tc1_interrupted_install_recovery(self, mock_env, run_install):
        """TC1: Interrupted install (partial files) -> Re-run update -> Success."""
        # 1. Simulate partial install
        mock_env["install_dir"].mkdir(parents=True)
        # Missing bootstrap, missing version
        
        # 2. Run update (Recovery)
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        assert (mock_env["install_dir"] / "bootstrap.sh").exists()
        assert (mock_env["install_dir"] / "VERSION").exists()

    def test_tc2_config_locked_recovery(self, mock_env, run_install):
        """TC2: Config file locked -> Install fails -> Unlock -> Install succeeds."""
        cfg = mock_env["ws1"] / ".codex" / "config.toml"
        cfg.chmod(0o444) # Lock
        
        # 1. Fail
        with pytest.raises(PermissionError):
            run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
            
        # 2. Unlock & Retry
        cfg.chmod(0o777)
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert "[mcp_servers.deckard]" in cfg.read_text()

    def test_tc3_workspace_move_handling(self, mock_env, run_install):
        """TC3: Workspace moved on disk -> Re-install updates paths."""
        # 1. Install in WS1
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        # 2. Simulate move (rename dir)
        # In test we just use ws2 as the "moved" location but verify paths update
        # If we run install in ws2, it should point to ws2
        
        run_install({"update": False, "yes": True}, cwd=mock_env["ws2"])
        
        cfg = mock_env["ws2"] / ".codex" / "config.toml"
        content = cfg.read_text()
        assert str(mock_env["ws2"]) in content
        assert str(mock_env["ws1"]) not in content

    def test_tc4_manual_uninstall_vs_script(self, mock_env, run_install):
        """TC4: User `rm -rf` install dir -> install.py detects and reinstalls."""
        # 1. Install
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        # 2. Manual Nuke
        shutil.rmtree(mock_env["install_dir"])
        
        # 3. Install (should detect missing dir and global install)
        # "update": False means "install if missing".
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert mock_env["install_dir"].exists()

    def test_tc5_rapid_install_update_loop(self, mock_env, run_install):
        """TC5: Install -> Update -> Update -> Update (Stress)."""
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        assert (mock_env["install_dir"] / "bootstrap.sh").exists()
        # Verify config isn't duplicated 3 times
        cfg = mock_env["ws1"] / ".codex" / "config.toml"
        assert cfg.read_text().count("command =") == 1
