import pytest
import os
import shutil
from pathlib import Path
from sari.core.settings import Settings, settings as global_settings
from sari.core.db.main import LocalSearchDB
from sari.core.workspace import WorkspaceManager

@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    """Clean environment for each test."""
    monkeypatch.setenv("SARI_RESPONSE_COMPACT", "0")
    monkeypatch.setenv("SARI_LOG_LEVEL", "DEBUG")
    # Enable FTS for all tests by default
    monkeypatch.setenv("SARI_ENABLE_FTS", "1")
    
    # Isolate global registry and config
    monkeypatch.setenv("SARI_REGISTRY_FILE", str(tmp_path / "registry.json"))
    monkeypatch.setenv("SARI_CONFIG", str(tmp_path / "config.json"))
    
    return monkeypatch

@pytest.fixture
def temp_workspace(tmp_path, monkeypatch):
    """Creates a temporary workspace with basic structure."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".sari").mkdir()
    (ws / "src").mkdir()
    # Correctly formatted multiline string
    code = "def hello():\n    print('world')"
    (ws / "src" / "main.py").write_text(code, encoding="utf-8")
    (ws / "README.md").write_text("# Test Project", encoding="utf-8")
    
    # Create explicit config to include .py files
    import json
    config_data = {
        "include_ext": [".py", ".md", ".json"],
        "profiles": ["core", "python"], # Force python profile
        "manual_only": False
    }
    (ws / ".sari" / "config.json").write_text(json.dumps(config_data), encoding="utf-8")
    
    # Isolate CWD to prevent indexing the actual repo
    monkeypatch.chdir(ws)
    return ws

@pytest.fixture

def db(temp_workspace, mock_env):

    """Creates a fresh DB initialized with the schema."""

    db_path = temp_workspace / ".sari" / "index.db"

    return LocalSearchDB(str(db_path))
