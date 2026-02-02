import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
import os

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound14UninstallDeep:
    """Round 14: Deep Uninstall & Cleanup"""

    def test_tc1_remove_pycache(self, mock_env):
        """TC1: Uninstall should remove __pycache__ directories if scattered?"""
        # install.py deletes the whole directory, so pycache inside it goes.
        # But what about pycache in workspace? Deckard doesn't put pycache in workspace.
        # So verifying INSTALL_DIR removal is enough.
        
        mock_env["install_dir"].mkdir(parents=True)
        (mock_env["install_dir"] / "__pycache__").mkdir()
        (mock_env["install_dir"] / "__pycache__" / "stuff.pyc").touch()
        
        args = type('Args', (), {"uninstall": True, "yes": True})()
        
        with patch("install._list_deckard_pids", return_value=[]), \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             
             # Need to patch cwd
             old_cwd = os.getcwd()
             os.chdir(mock_env["ws1"])
             try:
                 install.do_uninstall(args)
             finally:
                 os.chdir(old_cwd)
                 
        assert not mock_env["install_dir"].exists()

    def test_tc2_uninstall_keeps_data(self, mock_env):
        """TC2: Uninstall should NOT remove external data directory (if any)."""
        # Deckard data is usually in workspace/.codex/tools/deckard/data
        # This test ensures uninstall logic doesn't touch workspace data.
        data_dir = mock_env["ws1"] / ".codex" / "tools" / "deckard" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "index.db").touch()
        
        args = type('Args', (), {"uninstall": True, "yes": True})()
        
        with patch("install._list_deckard_pids", return_value=[]), \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             os.chdir(mock_env["ws1"])
             install.do_uninstall(args)
             
        assert (data_dir / "index.db").exists()

    def test_tc3_uninstall_missing_dir_ok(self, mock_env):
        """TC3: Uninstall should pass if directory is already gone."""
        # mock_env["install_dir"] does not exist by default in fixture setup?
        # fixture creates path object but mkdir logic depends.
        # conftest doesn't mkdir install_dir unless explicitly done.
        
        args = type('Args', (), {"uninstall": True, "yes": True, "quiet": True})()
        install.do_uninstall(args) # No error

    def test_tc4_uninstall_stops_daemons_gracefully(self, mock_env):
        """TC4: Daemon termination should handle AccessDenied."""
        # _terminate_pids logic check
        mock_env["install_dir"].mkdir(parents=True)
        args = type('Args', (), {"uninstall": True, "yes": True})()
        
        with patch("install._list_deckard_pids", return_value=[123]), \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])), \
             patch("os.kill", side_effect=PermissionError):
             
             # Should not crash
             os.chdir(mock_env["ws1"])
             install.do_uninstall(args)

    def test_tc5_uninstall_removes_codex_gemini_blocks(self, mock_env):
        """TC5: Verify exact block removal from config files."""
        # This duplicates earlier test but focusing on "Deep Clean" - ensuring remnants are gone
        cfg = mock_env["ws1"] / ".codex" / "config.toml"
        cfg.write_text("[mcp_servers.deckard]\ncmd='x'\n[other]\nval=1")
        
        args = type('Args', (), {"uninstall": True, "yes": True})()
        
        with patch("install._list_deckard_pids", return_value=[]), \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             os.chdir(mock_env["ws1"])
             install.do_uninstall(args)
             
        assert "[mcp_servers.deckard]" not in cfg.read_text()
        assert "[other]" in cfg.read_text()
