import os
import subprocess
import sys
import shutil
from pathlib import Path
import pytest

@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ux_workspace"
    ws.mkdir()
    return ws

def run_cli(args, cwd, env=None):
    if env is None:
        env = os.environ.copy()
    
    # Resolve project root relative to this test file
    project_root = Path(__file__).resolve().parent.parent.parent
    env["PYTHONPATH"] = str(project_root)
    
    cmd = [sys.executable, "-m", "mcp.cli"] + args
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)

def test_init_ux(workspace):
    """Verify init command feedback and file creation."""
    res = run_cli(["init"], workspace)
    
    assert res.returncode == 0
    assert "✅ Updated Deckard config" in res.stdout
    assert "🚀 Workspace initialized successfully" in res.stdout

    from app.workspace import WorkspaceManager
    cfg_path = Path(WorkspaceManager.resolve_config_path(str(workspace)))
    assert cfg_path.exists()
    
    # Run again without force
    res2 = run_cli(["init"], workspace)
    assert "✅ Updated Deckard config" in res2.stdout

def test_status_no_daemon_ux(workspace):
    """Verify status command feedback when daemon is missing."""
    # Ensure init first
    run_cli(["init"], workspace)
    
    # v2.7.0: Force a non-existent port to ensure connection failure during test
    env = os.environ.copy()
    env["DECKARD_PORT"] = "59999" 
    
    res = run_cli(["status"], workspace, env=env)
    
    assert res.returncode == 1
    assert "❌ Error" in res.stdout
    assert "Daemon is not running" in res.stdout or "Could not connect" in res.stdout

def test_doctor_ux(workspace):
    """Verify doctor command output structure."""
    project_root = Path(__file__).resolve().parent.parent.parent
    doctor_path = str(project_root / "doctor.py")
    
    cmd = [sys.executable, doctor_path]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    
    res = subprocess.run(cmd, cwd=str(workspace), env=env, capture_output=True, text=True)
    assert "Workspace Root" in res.stdout
