import json
import os
import time
import pytest
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch
from sari.mcp.tools.doctor import execute_doctor

class TestDoctorSelfHealing:
    
    @pytest.fixture
    def doctor_env(self, tmp_path):
        fake_home = tmp_path / "doctor_home"
        fake_home.mkdir()
        
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "doctor_registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        env["SARI_VERSION"] = "1.0.0"
        env["SARI_FORMAT"] = "json"
        # Use a high port to avoid real daemon interference
        env["SARI_DAEMON_PORT"] = "48999"
        
        return env

    def test_doctor_heals_stale_pid(self, doctor_env):
        pid_dir = Path(doctor_env["HOME"]) / ".local" / share_path()
        pid_dir.mkdir(parents=True, exist_ok=True)
        pid_file = pid_dir / "daemon.pid"
        pid_file.write_text("999999")
        
        with patch.dict("os.environ", doctor_env):
            res = execute_doctor({"auto_fix": False})
            data = json.loads(res["content"][0]["text"])
            
            daemon_res = next(r for r in data["results"] if r["name"] == "Sari Daemon")
            assert not daemon_res["passed"]
            assert "stale PID" in daemon_res["error"]
            
            res = execute_doctor({"auto_fix": True})
            data = json.loads(res["content"][0]["text"])
            
            fix_res = next(r for r in data["auto_fix"] if "Sari Daemon" in r["name"])
            assert fix_res["passed"]
            assert "removed" in fix_res["error"]
            
            assert not pid_file.exists()

    def test_doctor_heals_corrupted_registry(self, doctor_env):
        reg_file = Path(doctor_env["SARI_REGISTRY_FILE"])
        reg_file.parent.mkdir(parents=True, exist_ok=True)
        # Create a real corrupted state: valid JSON but wrong version or schema
        # Actually, let's mock ServerRegistry._load to fail
        with patch("sari.core.server_registry.ServerRegistry._load", side_effect=Exception("Corrupt")):
            with patch.dict("os.environ", doctor_env):
                res = execute_doctor({"auto_fix": True})
                data = json.loads(res["content"][0]["text"])
                
                fix_res = next(r for r in data["auto_fix"] if "Registry" in r["name"])
                assert fix_res["passed"]

    def test_doctor_detects_version_mismatch(self, doctor_env):
        with patch("sari.mcp.tools.doctor._identify_sari_daemon") as mock_id:
            with patch("sari.mcp.cli.read_pid", return_value=123):
                mock_id.return_value = {"name": "sari", "version": "0.0.1", "draining": False}
                
                with patch.dict("os.environ", doctor_env):
                    res = execute_doctor({"auto_fix": False})
                    data = json.loads(res["content"][0]["text"])
                    
                    daemon_res = next(r for r in data["results"] if r["name"] == "Sari Daemon")
                    assert not daemon_res["passed"]
                    assert "Version mismatch" in daemon_res["error"]

def share_path():
    return os.path.join("share", "sari")