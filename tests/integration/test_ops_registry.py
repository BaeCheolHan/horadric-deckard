
import pytest
import os
import json
import fcntl
import threading
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

# Paths adjustment
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from app.registry import ServerRegistry
from mcp.cli import _get_http_host_port
import app.http_server

class TestOpsRegistry:
    """
    Phase 2: Shield 2 (Ops/Reliability) Tests.
    Verifies ServerRegistry, Port Allocation, and CLI Resolution.
    """

    @pytest.fixture
    def registry(self, tmp_path):
        """Fixture for isolated registry."""
        registry_dir = tmp_path / ".local" / "share" / "horadric-deckard"
        registry_dir.mkdir(parents=True)
        registry_file = registry_dir / "server.json"
        
        # Patch the global path in app.registry
        with patch('app.registry.REGISTRY_FILE', registry_file):
            yield ServerRegistry()

    def test_registry_lifecycle(self, registry):
        """Test register, get, unregister flow."""
        ws_root = "/tmp/test_workspace"
        pid = 12345
        port = 50000
        
        # Register
        registry.register(ws_root, port, pid)
        
        # Get
        inst = registry.get_instance(ws_root)
        # Mock liveness check or use real PID (using os.getpid() is safer)
        # But here we just want to check persistence.
        # Wait, get_instance checks liveness. Let's use our own PID.
        my_pid = os.getpid()
        registry.register(ws_root, port, my_pid)
        
        inst = registry.get_instance(ws_root)
        assert inst is not None
        assert inst["port"] == port
        assert inst["pid"] == my_pid
        
        # Unregister
        registry.unregister(ws_root)
        inst = registry.get_instance(ws_root)
        assert inst is None or not registry._load().get("instances", {}).get(ws_root)

    def test_find_free_port(self, registry):
        """Test port allocation logic."""
        # Occupy a port in registry
        ws_root = "/tmp/test_port_alloc"
        port1 = 48888
        registry.register(ws_root, port1, os.getpid())
        
        # Should allocate next port
        port2 = registry.find_free_port(start_port=port1)
        assert port2 != port1
        assert port2 > port1

    def test_cli_resolution(self, registry, tmp_path):
        """Test that CLI finds the port from registry."""
        ws_root = str(tmp_path / "mock_ws")
        Path(ws_root).mkdir()
        port = 49999
        
        # Register in our isolated registry
        registry.register(ws_root, port, os.getpid())
        
        # Patch WorkspaceManager to return our mock root
        with patch('app.workspace.WorkspaceManager.resolve_workspace_root', return_value=ws_root):
            # Patch ServerRegistry in mcp.cli to refer to our test registry (by file path)
            # Actually we need to patch REGISTRY_FILE in mcp.cli import too if it imports it?
            # mcp.cli imports ServerRegistry from app.registry.
            # We already patched app.registry.REGISTRY_FILE globally in fixture? 
            # Pytest patching is per-test but import module attributes persist if not handled carefully.
            # But 'registry' fixture patches it in 'app.registry'. 'mcp.cli' uses 'app.registry'.
            # So it should work if mcp.cli imports module 'app.registry' and accesses attributes,
            # or if it imports class and class sends request to file.
            
            # Re-patching to be safe
            registry_file = registry._load.__globals__['REGISTRY_FILE'] # Hack to get path
            
            with patch('app.registry.REGISTRY_FILE', registry_file):
                 host, resolved_port = _get_http_host_port()
                 assert resolved_port == port
