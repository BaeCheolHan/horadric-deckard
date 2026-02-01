
import pytest
import os
import json
import logging
from unittest.mock import patch, MagicMock
from app.config import Config

class TestReviewRound9:
    """Round 9: Config Loader Tests."""

    @pytest.fixture
    def config_file(self, tmp_path):
        data = {
            "workspace_root": str(tmp_path),
            "redact_enabled": False
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)

    def test_load_basic(self, config_file):
        """Test 1: Basic load works."""
        cfg = Config.load(config_file)
        assert cfg.redact_enabled is False
        assert cfg.commit_batch_size == 500 # Default

    def test_workspace_override(self, config_file):
        """Test 2: workspace_root_override param works."""
        cfg = Config.load(config_file, workspace_root_override="/new/root")
        assert cfg.workspace_root == "/new/root"

    def test_port_override(self, config_file):
        """Test 3: Env var overrides port."""
        with patch.dict(os.environ, {"DECKARD_PORT": "12345"}):
            cfg = Config.load(config_file)
            assert cfg.server_port == 12345

    def test_db_path_relative_ignore(self, config_file):
        """Test 4: Relative DB path in env var should be ignored (or default used?)"""
        # Code warning but falls back to default logic.
        
        # If I set DECKARD_DB_PATH="relative/path"
        with patch.dict(os.environ, {"DECKARD_DB_PATH": "rel/db.sqlite"}):
            # Also clear fallback keys
            cfg = Config.load(config_file)
            # Should NOT be rel/db.sqlite
            assert "rel/db.sqlite" not in cfg.db_path
            # It should be workspace default
            assert ".codex/tools/deckard/data/index.db" in cfg.db_path

    def test_db_path_absolute(self, config_file):
        """Test 5: Absolute DB path in env var is accepted."""
        abs_path = "/tmp/my.db"
        with patch.dict(os.environ, {"DECKARD_DB_PATH": abs_path}):
            cfg = Config.load(config_file)
            assert cfg.db_path == abs_path
