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
    assert "✅ Created workspace marker" in res.stdout
    assert "✅ Created Deckard config" in res.stdout
    assert "🚀 Workspace initialized successfully" in res.stdout
    
    assert (workspace / ".codex-root").exists()
    assert (workspace / ".codex/tools/deckard/config/config.json").exists()
    
    # Run again without force
    res2 = run_cli(["init"], workspace)
    assert "ℹ️  Workspace marker already exists" in res2.stdout
    assert "ℹ️  Deckard config already exists" in res2.stdout

def test_status_no_daemon_ux(workspace):
    """Verify status command feedback when daemon is missing."""
    # Ensure init first
    run_cli(["init"], workspace)
    
    res = run_cli(["status"], workspace)
    
    assert res.returncode == 1
    assert "❌ Error: Could not connect to Deckard HTTP server" in res.stdout
    assert "Hint: Make sure the Deamon is running" in res.stdout

def test_doctor_ux(workspace):
    """Verify doctor command output structure and marker check."""
    project_root = Path(__file__).resolve().parent.parent.parent
    doctor_path = str(project_root / "doctor.py")
    
    # 1. Fail Case (No marker)
    cmd = [sys.executable, doctor_path]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    
    res = subprocess.run(cmd, cwd=str(workspace), env=env, capture_output=True, text=True)
    assert "FAIL" in res.stdout
    assert "Workspace Marker (.codex-root)" in res.stdout
    
    # 2. Pass Case (After init)
    run_cli(["init"], workspace)
    res2 = subprocess.run(cmd, cwd=str(workspace), env=env, capture_output=True, text=True)
    assert "PASS" in res2.stdout
    assert "Workspace Marker (.codex-root)" in res2.stdout
