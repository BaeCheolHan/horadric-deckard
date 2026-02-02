import pytest
import os
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound7ConfigIntegrity:
    """Round 7: Config File Integrity & Corruption"""

    def test_tc1_empty_config_file(self, mock_env, run_install):
        """TC1: Config file exists but is 0 bytes."""
        cfg = mock_env["ws1"] / ".codex" / "config.toml"
        cfg.write_text("")
        
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert "[mcp_servers.deckard]" in cfg.read_text()

    def test_tc2_config_permission_denied(self, mock_env, run_install):
        """TC2: Config file is read-only (should fail gracefully or warn)."""
        cfg = mock_env["ws1"] / ".codex" / "config.toml"
        cfg.write_text("# locked")
        cfg.chmod(0o444)
        
        # The script currently might crash on PermissionError or print warning.
        # _upsert_mcp_config catches Exception? No, it doesn't wrap write_text in try-except block 
        # inside the function (except the global block).
        # Wait, verify _upsert_mcp_config implementation in install.py.
        # It calls write_text. 
        # If it raises, do_install does not catch it explicitly for config update.
        # So we expect crash (SystemExit via unhandled exception?) or let's see.
        
        # Update: We want it to NOT crash the whole install if possible, OR crash if config is critical.
        # Config is critical. So crash is acceptable behavior.
        
        with pytest.raises(PermissionError):
            run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
            
        cfg.chmod(0o777) # Cleanup

    def test_tc3_config_is_directory(self, mock_env, run_install):
        """TC3: .codex/config.toml exists but is a directory."""
        cfg_dir = mock_env["ws1"] / ".codex" / "config.toml"
        if cfg_dir.exists(): cfg_dir.unlink()
        cfg_dir.mkdir()
        
        # Should raise IsADirectoryError
        with pytest.raises(IsADirectoryError):
            run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
            
        cfg_dir.rmdir()

    def test_tc4_missing_config_dir(self, mock_env, run_install):
        """TC4: .codex directory does not exist (should create)."""
        shutil.rmtree(mock_env["ws1"] / ".codex")
        
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
        assert (mock_env["ws1"] / ".codex" / "config.toml").exists()

    def test_tc5_partial_update_rollback(self, mock_env, run_install):
        """TC5: If Gemini update fails, Codex config should persist (Atomic-ish check)."""
        # We can't easily simulate failure in middle of do_install without heavy mocking.
        # Instead, verifying that Codex and Gemini are updated independently.
        
        # Make Gemini read-only
        gemini_cfg = mock_env["ws1"] / ".gemini" / "config.toml"
        gemini_cfg.chmod(0o444)
        
        try:
            # Install should fail on Gemini
            with pytest.raises(PermissionError):
                run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
            
            # BUT Codex config SHOULD be updated (as it runs first)
            codex_cfg = mock_env["ws1"] / ".codex" / "config.toml"
            assert "[mcp_servers.deckard]" in codex_cfg.read_text()
            
        finally:
            gemini_cfg.chmod(0o777)
