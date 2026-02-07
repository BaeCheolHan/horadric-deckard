import pytest
import asyncio
import os
from unittest.mock import MagicMock, patch
from sari.mcp.daemon import SariDaemon

@pytest.mark.asyncio
async def test_daemon_init():
    daemon = SariDaemon()
    assert daemon.boot_id is not None
    assert daemon.port > 0

@pytest.mark.asyncio
async def test_daemon_start_mock(tmp_path):
    # Mock PID_FILE location
    with patch('sari.mcp.daemon.PID_FILE', tmp_path / "daemon.pid"):
        daemon = SariDaemon()
        daemon.host = "127.0.0.1"
        daemon.port = 47779
        
        with patch('asyncio.start_server') as mock_start:
            mock_server = MagicMock()
            mock_start.return_value = mock_server
            
            # Use a task to start daemon and then cancel it
            task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)
            
            assert mock_start.called
            daemon.shutdown()
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass

def test_daemon_cleanup_legacy_pid(tmp_path):
    with patch('sari.mcp.daemon.PID_FILE', tmp_path / "daemon.pid"):
        daemon = SariDaemon()
        legacy = tmp_path / "daemon.pid"
        legacy.write_text("1234")
        daemon._cleanup_legacy_pid_file()
        assert not legacy.exists()
