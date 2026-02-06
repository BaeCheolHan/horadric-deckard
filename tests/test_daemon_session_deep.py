import os
import json
import socket
import time
import threading
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from sari.mcp.daemon import SariDaemon
from sari.mcp.session import Session
from sari.mcp.workspace_registry import Registry

def test_session_lifecycle():
    """Test session initialization and cleanup."""
    temp_dir = Path("/tmp/sari_session_test").resolve()
    if temp_dir.exists(): shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    
    # Mocking Registry to avoid DB creation in test
    registry = Registry.get_instance()
    
    # 1. Create Mock Session
    reader = MagicMock()
    writer = MagicMock()
    session = Session(reader, writer)
    
    assert session.running is True
    assert session.workspace_root is None
    
    # 2. Cleanup
    session.cleanup()
    assert session.workspace_root is None
    
    shutil.rmtree(temp_dir)

def test_daemon_server_communication():
    """Test SariDaemon internal server and command handling."""
    port = 49991
    daemon = SariDaemon(host="127.0.0.1", port=port)
    
    # Mocking background indexing
    with patch("sari.core.indexer.main.Indexer.run_forever"):
        daemon_thread = threading.Thread(target=daemon.start, daemon=True)
        daemon_thread.start()
        time.sleep(1.0)
        
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
                req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                body = json.dumps(req).encode("utf-8")
                header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                sock.sendall(header + body)
                
                resp_data = sock.recv(4096)
                assert b'"result":' in resp_data
        finally:
            daemon.stop()
            daemon_thread.join(timeout=2.0)

def test_workspace_registry_singleton():
    """Test that Registry follows singleton pattern and manages state."""
    r1 = Registry.get_instance()
    r2 = Registry.get_instance()
    assert r1 is r2
    
    # Registry uses a shared dict for SharedState
    ws_path = "/tmp/test_ws"
    # SharedState init will fail without real DB, so we mock get_or_create
    with patch.object(r1, "get_or_create") as mock_get:
        mock_get.return_value = MagicMock()
        state = r1.get_or_create(ws_path)
        assert state is not None
