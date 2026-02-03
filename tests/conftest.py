import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _deckard_test_isolation(monkeypatch, tmp_path, request):
    """
    Hard isolation so unit tests never touch a real running daemon or real
    user directories. Tests can explicitly override with monkeypatch if needed.
    """
    # Force testing mode + local-only endpoints
    monkeypatch.setenv("DECKARD_TESTING", "1")
    node_path = str(getattr(request.node, "fspath", "") or "")
    is_e2e_or_integration = "/tests/e2e/" in node_path or "/tests/integration/" in node_path

    monkeypatch.setenv("DECKARD_DAEMON_HOST", "127.0.0.1")
    if not is_e2e_or_integration:
        monkeypatch.setenv("DECKARD_DAEMON_PORT", "0")
        monkeypatch.setenv("DECKARD_HTTP_HOST", "127.0.0.1")
        monkeypatch.setenv("DECKARD_HTTP_PORT", "0")
    else:
        # Ensure e2e/integration uses registry instead of env overrides
        for key in [
            "DECKARD_HTTP_HOST",
            "LOCAL_SEARCH_HTTP_HOST",
            "DECKARD_HTTP_PORT",
            "LOCAL_SEARCH_HTTP_PORT",
            "DECKARD_PORT",
        ]:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DECKARD_ALLOW_NON_LOOPBACK", "0")
    monkeypatch.setenv("LOCAL_SEARCH_ALLOW_NON_LOOPBACK", "0")

    # Isolate workspace/log dirs to temp (skip for e2e/integration)
    if not is_e2e_or_integration:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", str(workspace_root))
        monkeypatch.setenv("LOCAL_SEARCH_WORKSPACE_ROOT", str(workspace_root))
        # Force config to a temp file to avoid leaking user config
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(
            '{"roots": ["%s"]}\n' % str(workspace_root).replace("\\", "\\\\"),
            encoding="utf-8",
        )
        monkeypatch.setenv("DECKARD_CONFIG", str(cfg_path))

    # Ensure DB path is not taken from user env
    monkeypatch.delenv("DECKARD_DB_PATH", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_DB_PATH", raising=False)
    monkeypatch.delenv("DECKARD_DATA_DIR", raising=False)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DECKARD_LOG_DIR", str(log_dir))

    allow_socket = (
        request.node.get_closest_marker("allow_socket") is not None
        or "/tests/e2e/" in node_path
        or "/tests/integration/" in node_path
    )
    if not allow_socket:
        # Block real sockets unless test explicitly overrides
        def _blocked_socket(*_args, **_kwargs):
            raise RuntimeError("Test isolation: socket.create_connection blocked (mock it in test).")

        monkeypatch.setattr(socket, "create_connection", _blocked_socket)

    allow_subprocess = (
        request.node.get_closest_marker("allow_subprocess") is not None
        or "/tests/e2e/" in node_path
        or "/tests/integration/" in node_path
    )
    if not allow_subprocess:
        # Block real subprocess spawn unless test explicitly overrides
        def _blocked_popen(*_args, **_kwargs):
            raise RuntimeError("Test isolation: subprocess.Popen blocked (mock it in test).")

        monkeypatch.setattr(subprocess, "Popen", _blocked_popen)

    if not is_e2e_or_integration:
        # Block real sys.exit so accidental exits don't terminate test run
        def _blocked_exit(code=0):
            raise RuntimeError(f"Test isolation: sys.exit blocked (code={code}).")

        monkeypatch.setattr(sys, "exit", _blocked_exit)


def pytest_collection_modifyitems(config, items):
    """Auto-tag slow/e2e/stress/history tests by path."""
    for item in items:
        path = str(getattr(item, "fspath", "") or "")
        if "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
            item.add_marker(pytest.mark.slow)
        if "/tests/history/" in path:
            item.add_marker(pytest.mark.history)
            item.add_marker(pytest.mark.slow)
        if "test_concurrency_stress.py" in path:
            item.add_marker(pytest.mark.stress)
            item.add_marker(pytest.mark.slow)
