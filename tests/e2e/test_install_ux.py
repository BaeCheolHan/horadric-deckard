
import pytest
import sys
import json
from unittest.mock import patch, MagicMock
from pathlib import Path
import subprocess

# Import install script logic (need to update path or reload)
# Since install.py is in root, we can import it if added to path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestShieldInstallUX:
    """
    Phase 2: Shield 1 (Installation/UX) Tests.
    Verifies quiet mode, json output, and error guidance.
    """

    @pytest.fixture
    def mock_sys_exit(self):
        with patch('sys.exit') as m:
            yield m

    @pytest.fixture
    def mock_subprocess(self):
        with patch('subprocess.run') as m:
            m.return_value.returncode = 0
            yield m

    def test_json_output_mode(self, capsys, tmp_path, mock_subprocess, mock_sys_exit):
        """Verify --json produces valid JSON lines."""
        # Setup configs
        install.INSTALL_DIR = tmp_path / "deckard"
        install.CONFIG["json"] = True
        install.CONFIG["quiet"] = False
        
        # Test print_success
        install.print_success("Test Install")
        
        captured = capsys.readouterr()
        
        # Parse output
        lines = captured.out.strip().split('\n')
        json_line = None
        for line in lines:
            if '"status": "success"' in line:
                json_line = line
                break
        
        assert json_line, "JSON success message not found"
        data = json.loads(json_line)
        assert data["message"] == "Test Install"
        assert data["status"] == "success"

    def test_quiet_mode_silence(self, capsys, tmp_path):
        """Verify --quiet suppresses stdout."""
        install.CONFIG["json"] = False
        install.CONFIG["quiet"] = True
        
        install.print_step("Silent Step")
        install.print_success("Silent Success")
        
        captured = capsys.readouterr()
        assert captured.out == "", "Quiet mode failed, output detected"

    def test_network_error_guidance(self, capsys, tmp_path):
        """Verify Smart Guide for Network Errors."""
        install.CONFIG["json"] = False
        install.CONFIG["quiet"] = False
        
        # Simulate Network Error
        error_msg = "fatal: limit exceeded: Could not resolve host: github.com"
        install.print_error(error_msg)
        
        captured = capsys.readouterr()
        
        # Check for user-friendly guide
        assert "[ERROR]" in captured.out
        assert "Network Error Detected!" in captured.out
        assert "HTTP_PROXY" in captured.out
        assert "DNS" in captured.out

    def test_permissions_error_guidance(self, capsys):
        """Verify Smart Guide for Permission Errors."""
        install.CONFIG["quiet"] = False
        error_msg = "Permission denied: access to .local/share"
        install.print_error(error_msg)
        
        captured = capsys.readouterr()
        
        assert "Permission Error Detected!" in captured.out
        assert "ownership" in captured.out
