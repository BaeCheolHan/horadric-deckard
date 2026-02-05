import os
import pytest
from sari.core.daemon_resolver import resolve_daemon_address, DEFAULT_PORT, DEFAULT_HOST
from sari.core.server_registry import ServerRegistry

def test_resolve_default():
    """No env, no registry -> Default."""
    # Ensure env is clean
    os.environ.pop("SARI_DAEMON_HOST", None)
    os.environ.pop("SARI_DAEMON_PORT", None)
    os.environ.pop("SARI_DAEMON_OVERRIDE", None)
    
    host, port = resolve_daemon_address("/tmp/fake-root")
    assert host == DEFAULT_HOST
    assert port == DEFAULT_PORT

def test_resolve_env_fallback():
    """Env set, no registry -> Env fallback."""
    os.environ["SARI_DAEMON_PORT"] = "55555"
    host, port = resolve_daemon_address("/tmp/fake-root")
    assert port == 55555
    os.environ.pop("SARI_DAEMON_PORT")

def test_resolve_registry_priority(monkeypatch, tmp_path):
    """Registry should beat Env fallback unless override is set."""
    # 1. Setup Registry
    reg_file = tmp_path / "server.json"
    monkeypatch.setenv("SARI_REGISTRY_FILE", str(reg_file))
    
    registry = ServerRegistry()
    ws_root = str(tmp_path / "ws")
    boot_id = "test-boot"
    registry.register_daemon(boot_id, "127.0.0.1", 44444, os.getpid())
    registry.set_workspace(ws_root, boot_id)
    
    # 2. Set Env Fallback (lower priority)
    monkeypatch.setenv("SARI_DAEMON_PORT", "55555")
    
    # 3. Resolve
    host, port = resolve_daemon_address(ws_root)
    assert port == 44444 # Should pick from registry
    
    # 4. Test Override (highest priority)
    monkeypatch.setenv("SARI_DAEMON_OVERRIDE", "1")
    host, port = resolve_daemon_address(ws_root)
    assert port == 55555 # Should pick from env now
