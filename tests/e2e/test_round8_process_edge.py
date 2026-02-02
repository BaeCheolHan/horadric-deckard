import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound8ProcessEdge:
    """Round 8: Process Management Edge Cases"""

    def test_tc1_zombie_process(self, mock_env, run_install):
        """TC1: Daemon process exists but os.kill raises Zombie error?"""
        # os.kill usually raises ProcessLookupError if pid gone, or PermissionError.
        # Zombie state allows kill (reaping).
        # We simulate OSError on kill.
        
        with patch("install._list_deckard_pids", return_value=[9999]), \
             patch("os.kill", side_effect=OSError("Resource temporarily unavailable")):
            
            # Should catch exception and proceed (best effort kill)
            run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])

        def test_tc2_multiple_daemons(self, mock_env):
            """TC2: Multiple running daemons should all be killed."""
            pids = [100, 101, 102]
            args = type('Args', (), {"update": True, "yes": True, "quiet": True})()
            
            # Manual patch to avoid fixture conflict
            with patch("install._list_deckard_pids", return_value=pids), \
                 patch("install._terminate_pids") as mock_term, \
                 patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])), \
                 patch("subprocess.run"), \
                 patch("subprocess.check_output", return_value="v1.0.0"):
                
                # Need to create install dir so it tries to update/remove
                mock_env["install_dir"].mkdir(parents=True, exist_ok=True)
                
                # Mock shutil.rmtree to avoid actual deletion error if dir exists
                with patch("shutil.rmtree"):
                    install.do_install(args)
                
                mock_term.assert_called_with(pids)
    
        def test_tc3_pid_file_locked(self, mock_env):
            """TC3: PID file check - if we implemented it in install.py?"""
            pass
    
        def test_tc4_sigint_handling(self, mock_env, run_install):
            """TC4: KeyboardInterrupt during install."""
            with patch("install._resolve_workspace_root", side_effect=KeyboardInterrupt):
                with pytest.raises(SystemExit):
                    install.do_install(type('Args', (), {"update": False, "yes": True})())
    
        def test_tc5_install_in_process_busy(self, mock_env, run_install):
            """TC5: Simulate 'Text file busy' (executable running) on Windows update."""
            # Ensure directory exists so removal logic is triggered
            mock_env["install_dir"].mkdir(parents=True, exist_ok=True)
            
            def rmtree_fail(path):
                raise PermissionError("The process cannot access the file because it is being used by another process")
        
            with patch("shutil.rmtree", side_effect=rmtree_fail):
                # Should fail and exit
                with pytest.raises(SystemExit):
                    run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
