import pytest
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# Add project root
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound5Integration:
    """Round 5: Full System Integration (Install -> Config -> Verify)"""

    def test_e2e_full_lifecycle(self, mock_env, run_install):
        """TC1: Full Cycle - Install, Update, Uninstall, Verify Clean State."""
        
        # 1. First Install
        print("[E2E] Step 1: Fresh Install")
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert mock_env["install_dir"].exists()
        assert (mock_env["ws1"] / ".codex" / "config.toml").exists()
        
        # 2. Configure Second Workspace
        print("[E2E] Step 2: Second Workspace")
        run_install({"update": False, "yes": True}, cwd=mock_env["ws2"])
        
        assert (mock_env["ws2"] / ".codex" / "config.toml").exists()
        
        # 3. Forced Update
        print("[E2E] Step 3: Forced Update")
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        # Verify version file update (mocked as v1.0.0, install strips 'v')
        assert (mock_env["install_dir"] / "VERSION").read_text().strip() == "1.0.0"
        
        # 4. Uninstall
        print("[E2E] Step 4: Uninstall")
        args = type('Args', (), {"uninstall": True, "yes": True})()
        
        with patch("install._list_deckard_pids", return_value=[]), \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             # Mock cwd for config finding
             old_cwd = os.getcwd()
             os.chdir(mock_env["ws1"])
             try:
                 install.do_uninstall(args)
             finally:
                 os.chdir(old_cwd)
                 
        # 5. Verify Cleanup
        print("[E2E] Step 5: Verification")
        assert not mock_env["install_dir"].exists()
        
        # Configs should be stripped
        codex_cfg = mock_env["ws1"] / ".codex" / "config.toml"
        assert "[mcp_servers.deckard]" not in codex_cfg.read_text()
        
        # WS2 configs should also be stripped IF uninstall logic hits global (which it attempts via HOME)
        # But uninstall currently targets CWD + HOME. WS2 is separate.
        # So WS2 config might remain "dirty" with invalid path until user runs clean there.
        # This is expected behavior (uninstall is per-user + current-workspace).
