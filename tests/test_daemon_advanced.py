import unittest
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.main import main

class TestDaemonAdvanced(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.tmp_dir) / "ws"
        self.workspace.mkdir()
        
        # WorkspaceManager.resolve_workspace_root mocks
        self.res_ws_patcher = patch("app.workspace.WorkspaceManager.resolve_workspace_root", return_value=str(self.workspace))
        self.res_ws_patcher.start()
        
        # Serve forever mock to avoid actual socket binding
        self.serve_patcher = patch("app.main.serve_forever", return_value=(MagicMock(), 47777))
        self.serve_patcher.start()

    def tearDown(self):
        self.serve_patcher.stop()
        self.res_ws_patcher.stop()
        shutil.rmtree(self.tmp_dir)

    def test_loopback_security_violation(self):
        """Should exit if host is not loopback and override env is missing."""
        mock_cfg = MagicMock()
        mock_cfg.server_host = "192.168.1.100"
        mock_cfg.server_port = 47777
        
        with patch("app.main.Config.load", return_value=mock_cfg), \
             patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertIn("must be loopback only", str(cm.exception))

    def test_indexer_stop_on_shutdown(self):
        """Verify indexer.stop() is called during shutdown."""
        mock_indexer = MagicMock()
        mock_httpd = MagicMock()
        
        with patch("app.main.Indexer", return_value=mock_indexer), \
             patch("app.main.serve_forever", return_value=(mock_httpd, 47777)), \
             patch("app.main.time.sleep", side_effect=InterruptedError):
            
            try:
                main()
            except (InterruptedError, SystemExit):
                pass
                
            self.assertTrue(mock_indexer.stop.called)
            self.assertTrue(mock_httpd.shutdown.called)

    def test_config_fallback_logic(self):
        """Verify defaults are used when config.json is missing."""
        with patch("app.main.os.path.exists", return_value=False), \
             patch("app.main.Config") as mock_config_class, \
             patch("app.main.time.sleep", side_effect=InterruptedError):
            
            try:
                main()
            except (InterruptedError, SystemExit):
                pass
            
            # Should have called Config(...) constructor with defaults
            self.assertTrue(mock_config_class.called)
            args, kwargs = mock_config_class.call_args
            self.assertEqual(kwargs.get('workspace_root') or args[1], str(self.workspace))
            self.assertEqual(kwargs.get('workspace_roots') or args[0], [str(self.workspace)])

if __name__ == "__main__":
    unittest.main()
