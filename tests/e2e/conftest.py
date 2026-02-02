import pytest
import os
import sys
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import install module
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
import install

@pytest.fixture
def mock_env(tmp_path):
    """
    Sets up a completely sandboxed environment for all rounds.
    Includes fake HOME, INSTALL_DIR, and Workspace.
    """
    # 1. Paths
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_install_dir = fake_home / ".local" / "share" / "horadric-deckard"
    ws1 = tmp_path / "ws1"
    ws1.mkdir()
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    
    # 2. Fake Repo (for cloning)
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "bootstrap.sh").write_text("#!/bin/bash\necho 'v1.0.0'")
    (fake_repo / "install.py").write_text("print('fake install')")
    (fake_repo / ".git").mkdir()

    # 3. Environment Overrides
    orig_home = os.environ.get("HOME")
    os.environ["HOME"] = str(fake_home)
    os.environ["DECKARD_NO_INTERACTIVE"] = "1"
    
    # Monkeypatch install module constants
    orig_install_dir = install.INSTALL_DIR
    orig_repo_url = install.REPO_URL
    install.INSTALL_DIR = fake_install_dir
    install.REPO_URL = str(fake_repo)
    
    # Helper to create config.toml to test upsert/remove
    (ws1 / ".codex").mkdir()
    (ws1 / ".codex" / "config.toml").write_text("")
    (ws1 / ".gemini").mkdir()
    (ws1 / ".gemini" / "config.toml").write_text("")

    yield {
        "home": fake_home,
        "install_dir": fake_install_dir,
        "ws1": ws1,
        "ws2": ws2,
        "repo": fake_repo
    }

    # Teardown
    if orig_home:
        os.environ["HOME"] = orig_home
    install.INSTALL_DIR = orig_install_dir
    install.REPO_URL = orig_repo_url

@pytest.fixture
def run_install():
    """Helper to run install.do_install with mocked subprocess"""
    def _run(args_dict, cwd):
        args = type('Args', (), args_dict)()
        
        # Patch things that touch the real system
        with patch("install._resolve_workspace_root", return_value=str(cwd)), \
             patch("subprocess.run") as mock_run, \
             patch("subprocess.check_output", return_value="v1.0.0"), \
             patch("install._terminate_pids"):
            
            # Simulate git clone copying files
            def side_effect(cmd, **kwargs):
                if cmd[0] == "git" and cmd[1] == "clone":
                    target = Path(cmd[-1])
                    if target.exists(): shutil.rmtree(target)
                    shutil.copytree(str(install.REPO_URL), target)
                return MagicMock(returncode=0)
            
            mock_run.side_effect = side_effect
            install.do_install(args)
            return mock_run
    return _run
