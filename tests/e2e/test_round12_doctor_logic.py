import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Doctor is in project root, not installed yet in tests usually, 
# but we can import it from the source tree.
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import doctor

class TestRound12DoctorLogic:
    """Round 12: Doctor Diagnostic Logic"""

    def test_tc1_check_network_dns_fail(self):
        """TC1: Network check fails on DNS resolution error."""
        with patch("socket.create_connection", side_effect=OSError("Name or service not known")):
            # Capture print output? 
            # check_network returns True/False
            assert doctor.check_network() is False

    def test_tc2_check_port_in_use(self):
        """TC2: Port check fails if port is bound."""
        # check_port tries to bind. If it raises OSError, it returns False.
        with patch("socket.socket") as mock_sock:
            mock_inst = MagicMock()
            mock_inst.bind.side_effect = OSError("Address in use")
            mock_sock.return_value = mock_inst
            
            assert doctor.check_port(47777) is False

    def test_tc3_check_disk_space_ok(self):
        """TC3: Disk space check passes if space > 1GB."""
        with patch("shutil.disk_usage", return_value=(10**10, 10**9, 2 * 10**9)): # 2GB free
            assert doctor.check_disk_space() is True

    def test_tc4_check_disk_space_low(self):
        """TC4: Disk space check fails if space < 1GB."""
        with patch("shutil.disk_usage", return_value=(10**10, 10**9, 0.5 * 10**9)): # 0.5GB free
            assert doctor.check_disk_space() is False

    def test_tc5_marker_check_fail(self, tmp_path):
        """TC5: Marker check fails if .codex-root is missing."""
        with patch("app.workspace.WorkspaceManager.resolve_workspace_root", return_value=str(tmp_path)):
            assert doctor.check_marker() is False
            
            (tmp_path / ".codex-root").touch()
            assert doctor.check_marker() is True
