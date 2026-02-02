
import os
import json
import pytest
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

@pytest.fixture
def temp_home(tmp_path):
    orig_home = os.environ.get("HOME")
    os.environ["HOME"] = str(tmp_path)
    yield tmp_path
    if orig_home:
        os.environ["HOME"] = orig_home

def test_upsert_mcp_config_both_clis(tmp_path):
    """Verify that _upsert_mcp_config handles .codex and gemini settings correctly."""
    codex_cfg = tmp_path / ".codex" / "config.toml"
    gemini_cfg = tmp_path / ".gemini" / "settings.json"
    
    install._upsert_mcp_config(codex_cfg, "/bin/deckard", "/workspace")
    install._upsert_gemini_settings(gemini_cfg, "/bin/deckard", "/workspace")
    
    assert codex_cfg.exists()
    assert gemini_cfg.exists()
    
    assert "[mcp_servers.deckard]" in codex_cfg.read_text()
    assert "command = \"/bin/deckard\"" in codex_cfg.read_text()
    data = json.loads(gemini_cfg.read_text())
    assert data["mcpServers"]["deckard"]["command"] == "/bin/deckard"

def test_remove_mcp_config_both_clis(tmp_path):
    """Verify that _remove_mcp_config cleans up both CLIs."""
    codex_cfg = tmp_path / ".codex" / "config.toml"
    gemini_cfg = tmp_path / ".gemini" / "settings.json"
    
    # Setup: Create configs with deckard block
    content = "[mcp_servers.deckard]\ncommand = \"/bin/deckard\"\n\n[other]\nkey = \"val\""
    codex_cfg.parent.mkdir(parents=True)
    codex_cfg.write_text(content)
    gemini_cfg.parent.mkdir(parents=True)
    gemini_cfg.write_text(json.dumps({"mcpServers": {"deckard": {"command": "/bin/deckard"}}, "other": "val"}))
    
    # Execute removal
    install._remove_mcp_config(codex_cfg)
    install._remove_gemini_settings(gemini_cfg)
    
    assert "[mcp_servers.deckard]" not in codex_cfg.read_text()
    assert "[other]" in codex_cfg.read_text()
    data = json.loads(gemini_cfg.read_text())
    assert "deckard" not in (data.get("mcpServers") or {})

def test_do_install_updates_both(tmp_path, monkeypatch):
    """Verify do_install targets both .codex and .gemini in workspace."""
    install.INSTALL_DIR = tmp_path / "deckard_inst"
    install.REPO_URL = "http://dummy"
    monkeypatch.setattr(install, "confirm", lambda x, default=True: True)
    monkeypatch.setattr(install, "_list_deckard_pids", lambda: [])
    monkeypatch.setattr(install, "_resolve_workspace_root", lambda: str(tmp_path))
    monkeypatch.setenv("DECKARD_NO_INTERACTIVE", "1")
    
    # Mock subprocess.run for git clone
    def mock_run_impl(cmd, **kwargs):
        if "clone" in cmd:
            install.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            (install.INSTALL_DIR / "bootstrap.sh").touch()
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run_impl):
        args = MagicMock()
        args.yes = True
        install.do_install(args)
    
    codex_ws_cfg = tmp_path / ".codex" / "config.toml"
    gemini_ws_cfg = tmp_path / ".gemini" / "settings.json"
    
    assert codex_ws_cfg.exists()
    assert gemini_ws_cfg.exists()
    assert "[mcp_servers.deckard]" in codex_ws_cfg.read_text()
    data = json.loads(gemini_ws_cfg.read_text())
    assert "deckard" in (data.get("mcpServers") or {})
