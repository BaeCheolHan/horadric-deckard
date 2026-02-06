import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from sari.mcp.tools.doctor import execute_doctor, _check_log_errors, _check_db_integrity

class TestProDoctorEdgeCases:
    
    @pytest.fixture
    def pro_env(self, tmp_path):
        fake_home = tmp_path / "pro_home"
        fake_home.mkdir()
        
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "pro_registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        
        log_dir = fake_home / ".local" / "share" / "sari" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        env["SARI_LOG_DIR"] = str(log_dir)
        
        return env

    def test_doctor_log_oom_safety(self, pro_env):
        log_file = Path(pro_env["SARI_LOG_DIR"]) / "daemon.log"
        with open(log_file, "wb") as f:
            f.write(b"INFO - Normal log line\n" * 1000) 
            f.write(b"ERROR - This is a critical error at the end\n")
            
        with patch.dict("os.environ", pro_env):
            res = _check_log_errors()
            # It should return passed=False if errors are found
            assert not res["passed"]
            assert "error" in res["error"].lower()

    def test_doctor_db_corruption_handling(self, tmp_path, pro_env):
        empty_db = tmp_path / "empty.db"
        empty_db.write_bytes(b"")
        
        with patch("sari.core.workspace.WorkspaceManager.resolve_config_path", return_value=""), \
             patch("sari.core.config.Config.load") as mock_load:
            
            mock_cfg = MagicMock()
            mock_cfg.db_path = str(empty_db)
            mock_load.return_value = mock_cfg
            
            res = _check_db_integrity("/tmp")
            assert not res["passed"]
            assert "0 bytes" in res["error"]
            
            junk_db = tmp_path / "junk.db"
            junk_db.write_text("THIS IS NOT SQLITE")
            mock_cfg.db_path = str(junk_db)
            
            res = _check_db_integrity("/tmp")
            assert not res["passed"]
            assert "Corruption" in res["error"] or "Check failed" in res["error"]

    def test_doctor_no_psutil_fallback(self, pro_env):
        # Mock psutil to be missing
        with patch.dict("sys.modules", {"psutil": None}):
            # Use the correct internal name after my refactoring
            with patch("sari.mcp.tools.doctor._cli_identify", return_value={"version":"1.0"}), \
                 patch("sari.mcp.cli.read_pid", return_value=1234):
                
                res = execute_doctor({"include_daemon": True})
                assert res is not None
                text = res["content"][0]["text"]
                assert "Sari Daemon" in text

    def test_doctor_registry_permission_denied(self, pro_env):
        reg_file = Path(pro_env["SARI_REGISTRY_FILE"])
        reg_file.parent.mkdir(parents=True, exist_ok=True)
        reg_file.write_text("{}")
        os.chmod(reg_file, 0o000) 
        
        try:
            with patch.dict("os.environ", pro_env):
                res = execute_doctor({"auto_fix": True})
                assert res is not None
        finally:
            os.chmod(reg_file, 0o666)
