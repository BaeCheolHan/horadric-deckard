import pytest
import os
import sys
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Project Root setup to import install.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
import install

@pytest.fixture
def mock_env(tmp_path):
    """Sets up a sandboxed environment for installation testing."""
    # 1. Mock HOME
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    
    # 2. Mock Install Dir
    fake_install_dir = fake_home / ".local" / "share" / "horadric-deckard"
    
    # 3. Mock Workspace 1 & 2
    ws1 = tmp_path / "workspace1"
    ws1.mkdir()
    ws2 = tmp_path / "workspace2"
    ws2.mkdir()
    
    # 4. Mock Local Source (Clone from current project to speed up)
    # We create a dummy git repo structure in tmp_path to simulate remote repo
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "install.py").write_text(PROJECT_ROOT.joinpath("install.py").read_text())
    (fake_repo / "bootstrap.sh").write_text("#!/bin/bash\necho 'bootstrap'")
    (fake_repo / ".git").mkdir() # Fake git dir
    
    # Apply Mocks via Monkeypatch logic (manual swap/restore)
    # But since install.py is a module, we modify its attributes directly
    
    orig_home = os.environ.get("HOME")
    orig_install_dir = install.INSTALL_DIR
    orig_repo_url = install.REPO_URL
    
    os.environ["HOME"] = str(fake_home)
    # We must also force install.py to re-evaluate paths based on new HOME if possible,
    # but install.py computes INSTALL_DIR at module level. We must override it.
    install.INSTALL_DIR = fake_install_dir
    install.CLAUDE_CONFIG_DIR = fake_home / "Claude"
    install.REPO_URL = str(fake_repo) # Clone from local fake repo
    
    # Environment variables for install script
    os.environ["DECKARD_NO_INTERACTIVE"] = "1"
    
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

def run_install(args_dict, cwd):
    """Helper to invoke do_install with mocked args."""
    args = type('Args', (), args_dict)()
    
    # Mock _resolve_workspace_root to return cwd
    with patch("install._resolve_workspace_root", return_value=str(cwd)):
        # Mock subprocess.run to simulate git clone if needed (or let it copy local)
        # Since we set REPO_URL to a local path, git clone might work if git is available.
        # But safer to mock clone to just copy files for speed/stability.
        def mock_subprocess_run(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "clone":
                target = Path(cmd[-1])
                if target.exists(): shutil.rmtree(target)
                shutil.copytree(str(install.REPO_URL), target)
                return MagicMock(returncode=0)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            with patch("subprocess.check_output", return_value="v1.0.0"):
                install.do_install(args)

def test_tc1_fresh_install(mock_env):
    """TC1: Fresh Install (Global + Workspace)"""
    args = {"update": False, "yes": True, "quiet": True}
    
    run_install(args, cwd=mock_env["ws1"])
    
    # Verify Global Install
    assert mock_env["install_dir"].exists()
    assert (mock_env["install_dir"] / "bootstrap.sh").exists()
    
    # Verify Workspace Config
    cfg = mock_env["ws1"] / ".codex" / "config.toml"
    assert cfg.exists()
    assert "[mcp_servers.deckard]" in cfg.read_text()

def test_tc2_multi_workspace_smart_skip(mock_env):
    """TC2: Secondary Workspace Install (Smart Skip)"""
    # 1. Install on WS1
    run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
    install_mtime = mock_env["install_dir"].stat().st_mtime
    
    # 2. Install on WS2 (Should be fast, no clone)
    # We patch subprocess.run. If git clone is called, we fail the test
    with patch("subprocess.run") as mock_run:
        run_install({"update": False, "yes": True}, cwd=mock_env["ws2"])
        
        # Verify git clone was NOT called
        for call in mock_run.call_args_list:
            args = call[0][0]
            if "git" in args and "clone" in args:
                pytest.fail("Git clone was called during secondary install! Smart Skip failed.")
    
    # Verify WS2 config created
    assert (mock_env["ws2"] / ".codex" / "config.toml").exists()
    assert (mock_env["ws2"] / ".gemini" / "config.toml").exists()

def test_tc3_update_flag_force_install(mock_env):
    """TC3: Update Flag Force Install"""
    # 1. Setup existing install with old file
    mock_env["install_dir"].mkdir(parents=True)
    (mock_env["install_dir"] / "bootstrap.sh").write_text("OLD VERSION")
    
    # 2. Run with --update
    run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
    
    # 3. Verify file replaced (our mock clone copies 'echo bootstrap')
    content = (mock_env["install_dir"] / "bootstrap.sh").read_text()
    assert "echo 'bootstrap'" in content
    assert "OLD VERSION" not in content

def test_tc4_uninstall_cleanup(mock_env):
    """TC4: Uninstall Cleanup (Gemini included)"""
    # 1. Setup full environment
    run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
    
    # Verify Setup
    assert (mock_env["ws1"] / ".gemini" / "config.toml").exists()
    
    # 2. Run Uninstall
    args = type('Args', (), {"uninstall": True, "yes": True})
    
    # We need to mock _list_deckard_pids to return empty to avoid killing real procs
    with patch("install._list_deckard_pids", return_value=[]):
        # We need to patch _resolve_workspace_root for uninstall too
        with patch("install._resolve_workspace_root", return_value=str(mock_env["ws1"])):
             # CRITICAL: Switch CWD so Path.cwd() inside install.py finds the correct config
             old_cwd = os.getcwd()
             os.chdir(mock_env["ws1"])
             try:
                 install.do_uninstall(args)
             finally:
                 os.chdir(old_cwd)
             
    # 3. Verify Removal
    assert not mock_env["install_dir"].exists()
    
    # Configs should be cleaned (stripped of deckard block)
    # Since they were created fresh, stripping deckard block might leave them empty or partial.
    # install.py deletes the block but keeps the file.
    
    gemini_cfg = mock_env["ws1"] / ".gemini" / "config.toml"
    assert gemini_cfg.exists() # File remains
    assert "[mcp_servers.deckard]" not in gemini_cfg.read_text() # Block gone

def test_tc5_broken_install_recovery(mock_env):
    """TC5: Broken Installation Recovery"""
    # 1. Setup broken install (dir exists, but bootstrap missing)
    mock_env["install_dir"].mkdir(parents=True)
    # No bootstrap.sh created
    
    # 2. Run Install (Normal)
    # It should detect missing bootstrap and trigger global install (or fail? Logic says fail currently)
    # Wait, the new logic: 
    #   if not INSTALL_DIR.exists(): ... global install
    #   else: ... skip
    #   Then checks if bootstrap exists. If not, exit(1).
    
    # Let's verify current behavior. 
    # Ideally, it should suggest --update or auto-recover.
    # Code review says: "Deckard is not installed correctly... run with --update flag."
    
    with pytest.raises(SystemExit):
        run_install({"update": False, "yes": True}, cwd=mock_env["ws1"])
        
    # 3. Run with --update (Recovery)
    run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
    
    assert (mock_env["install_dir"] / "bootstrap.sh").exists()
