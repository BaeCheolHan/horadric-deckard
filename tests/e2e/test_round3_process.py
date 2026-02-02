import pytest
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound3Process:
    """Round 3: Process Management & Bootstrap Permissions"""

    def test_tc1_install_kills_daemon(self, mock_env):
        """TC1: Running update should kill existing daemons."""
        args = type('Args', (), {"update": True, "yes": True, "quiet": True})()
        
        from unittest.mock import MagicMock
        from pathlib import Path
        import shutil

        def mock_clone_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "clone":
                target = Path(cmd[-1])
                if target.exists(): shutil.rmtree(target)
                shutil.copytree(str(install.REPO_URL), target)
            return MagicMock(returncode=0)

        with patch("install._list_deckard_pids", return_value=[12345]), \
             patch("install._terminate_pids") as mock_term, \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])), \
             patch("subprocess.run", side_effect=mock_clone_side_effect), \
             patch("subprocess.check_output", return_value="v1.0.0"):
            
            install.do_install(args)
            
            mock_term.assert_called_with([12345])

    def test_tc2_uninstall_stops_daemon(self, mock_env):
        """TC2: Uninstall should stop daemons."""
        mock_env["install_dir"].mkdir(parents=True, exist_ok=True)
        args = type('Args', (), {"uninstall": True, "yes": True})()
        
        with patch("install._list_deckard_pids", return_value=[999]), \
             patch("install._terminate_pids") as mock_term, \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
            
            install.do_uninstall(args)
            mock_term.assert_called_with([999])

    def test_tc3_bootstrap_permission_fix(self, mock_env, run_install):
        """TC3: Installer should ensure bootstrap.sh is executable."""
        if sys.platform == "win32":
            pytest.skip("Chmod test skipped on Windows")
            
        with patch("os.chmod") as mock_chmod:
            run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
            assert mock_chmod.called

    def test_tc4_version_file_generation(self, mock_env, run_install):
        """TC4: VERSION file should be generated after install."""
        run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
        
        assert (mock_env["install_dir"] / "VERSION").exists()
        assert (mock_env["install_dir"] / "VERSION").read_text().strip() == "1.0.0"

    def test_tc5_install_preserves_unrelated_pids(self, mock_env):
        """TC5: Should not kill unrelated python processes (Mock check)."""
        args = type('Args', (), {"update": True, "yes": True, "quiet": True})()
        
        from unittest.mock import MagicMock
        from pathlib import Path
        import shutil

        def mock_clone_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "clone":
                target = Path(cmd[-1])
                if target.exists(): shutil.rmtree(target)
                shutil.copytree(str(install.REPO_URL), target)
            return MagicMock(returncode=0)

        with patch("install._list_deckard_pids", return_value=[]), \
             patch("install._terminate_pids") as mock_term, \
             patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])), \
             patch("subprocess.run", side_effect=mock_clone_side_effect), \
             patch("subprocess.check_output", return_value="v1.0.0"):
            
            install.do_install(args)
            mock_term.assert_not_called()
