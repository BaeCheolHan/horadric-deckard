import pytest
import os
import json
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from app.registry import ServerRegistry

class TestRound13Registry:
    """Round 13: Registry File Stability"""

    def test_tc1_create_if_missing(self, mock_env):
        """TC1: Registry file created if missing."""
        reg_file = mock_env["home"] / "server.json"
        with patch("app.registry.REGISTRY_FILE", reg_file):
            reg = ServerRegistry()
            assert reg_file.exists()
            assert json.loads(reg_file.read_text())["version"] == "1.0"

    def test_tc2_corrupt_registry_reset(self, mock_env):
        """TC2: Corrupt registry file is reset on load/save."""
        reg_file = mock_env["home"] / "server.json"
        reg_file.write_text("{ not json }")
        
        with patch("app.registry.REGISTRY_FILE", reg_file):
            reg = ServerRegistry()
            # _load swallows error and returns empty dict
            assert reg.get_instance("/path") is None
            
            # Save should overwrite corruption
            reg.register("/path", 1234, 5678)
            assert json.loads(reg_file.read_text())["instances"]

    def test_tc3_dead_process_cleanup(self, mock_env):
        """TC3: get_instance returns None for dead PID."""
        reg_file = mock_env["home"] / "server.json"
        with patch("app.registry.REGISTRY_FILE", reg_file):
            reg = ServerRegistry()
            reg.register("/ws", 8080, 99999) # Fake PID
            
            # Mock os.kill to raise ProcessLookupError
            with patch("os.kill", side_effect=ProcessLookupError):
                inst = reg.get_instance("/ws")
                assert inst is None

    def test_tc4_register_overwrite(self, mock_env):
        """TC4: Registering same workspace updates port/pid."""
        reg_file = mock_env["home"] / "server.json"
        with patch("app.registry.REGISTRY_FILE", reg_file):
            reg = ServerRegistry()
            reg.register("/ws", 8080, 100)
            reg.register("/ws", 9090, 200)
            
            inst = reg._load()["instances"]["/ws"]
            assert inst["port"] == 9090
            assert inst["pid"] == 200

    def test_tc5_registry_lock_mock(self, mock_env):
        """TC5: Verify locking logic calls (mocked)."""
        reg_file = mock_env["home"] / "server.json"
        # On Windows, we skip fcntl. On Unix, we use it.
        # We assume Unix environment for these tests usually.
        if sys.platform == "win32":
            pytest.skip("Locking test skipped on Windows")
            
        with patch("app.registry.REGISTRY_FILE", reg_file), \
             patch("fcntl.flock") as mock_lock:
            reg = ServerRegistry()
            reg.register("/ws", 1, 1)
            assert mock_lock.called
