import json
import os
import time
import pytest
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
from sari.mcp.tools.doctor import execute_doctor, _check_log_errors, _check_db_integrity

class TestBrokenScenarios:
    
    @pytest.fixture
    def env(self, tmp_path):
        fake_home = tmp_path / "broken_home"
        fake_home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "broken_registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        # Setup log dir
        log_dir = fake_home / ".local" / share_path() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        env["SARI_LOG_DIR"] = str(log_dir)
        env["SARI_FORMAT"] = "json"
        return env

    def test_scenario_locked_db(self, tmp_path, env):
        db_file = tmp_path / "locked.db"
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE t(id)")
        conn.execute("BEGIN EXCLUSIVE")
        
        with patch("sari.core.config.Config.load") as mock_load:
            mock_cfg = MagicMock()
            mock_cfg.db_path = str(db_file)
            mock_load.return_value = mock_cfg
            
            with patch.dict("os.environ", env):
                res = _check_db_integrity("/tmp")
                assert not res["passed"]
                # SQLite locked error message
                assert any(x in res["error"].lower() for x in ["locked", "failed", "busy"])
        
        conn.close()

    def test_scenario_disk_full(self, env):
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = (1000, 1000, 0)
            with patch.dict("os.environ", env):
                res = execute_doctor({"include_disk": True})
                data = json.loads(res["content"][0]["text"])
                disk_res = next(r for r in data["results"] if r["name"] == "Disk Space")
                assert not disk_res["passed"]

    def test_scenario_missing_dependencies(self, env):
        # Simulate missing tantivy by patching sys.modules
        with patch.dict("sys.modules", {"tantivy": None}):
            with patch.dict("os.environ", env):
                res = execute_doctor({"include_db": True})
                data = json.loads(res["content"][0]["text"])
                dep_res = next(r for r in data["results"] if "Embedded Engine Module" in r["name"])
                assert not dep_res["passed"]

    def test_scenario_registry_migration_v1(self, env):
        reg_file = Path(env["SARI_REGISTRY_FILE"])
        old_data = {
            "instances": {
                "/tmp/old_ws": {"pid": 123, "port": 47777, "start_ts": 1000}
            }
        }
        reg_file.write_text(json.dumps(old_data))
        
        # We need to ensure the registry module uses OUR reg_file
        import sari.core.server_registry as sr
        with patch.object(sr, "REGISTRY_FILE", reg_file):
            with patch.dict("os.environ", env):
                registry = sr.ServerRegistry()
                data = registry._load()
                assert data["version"] == "2.0"
                assert len(data["workspaces"]) > 0

def share_path():
    return os.path.join("share", "sari")
