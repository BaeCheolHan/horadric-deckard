
import os
import sys
import json
import shutil
import subprocess
import time
import signal
from pathlib import Path
import pytest

# Add current project root to PYTHONPATH to import install.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
import install

@pytest.fixture
def test_env(tmp_path):
    """Setup a controlled test environment with temp HOME and Workspace."""
    test_root = tmp_path / "deckard_e2e"
    test_root.mkdir()
    
    mock_home = test_root / "home"
    mock_home.mkdir()
    
    workspace = test_root / "workspace"
    workspace.mkdir()
    
    # Override INSTALL_DIR for the test
    orig_install_dir = install.INSTALL_DIR
    install.INSTALL_DIR = mock_home / ".local" / "share" / "horadric-deckard"

    # Force install.py to see the new HOME for path evaluations
    orig_home = os.environ.get("HOME")
    os.environ["HOME"] = str(mock_home)
    
    # Reload install to re-evaluate module level paths
    import importlib
    importlib.reload(install)
    
    # Override again if needed (or ensure it picked up mock_home)
    install.INSTALL_DIR = mock_home / ".local" / "share" / "horadric-deckard"
    
    os.environ["DECKARD_INSTALL_SOURCE"] = str(PROJECT_ROOT)
    os.environ["DECKARD_NO_INTERACTIVE"] = "1"
    os.environ["DECKARD_WORKSPACE_ROOT"] = str(workspace)
    
    yield {
        "root": test_root,
        "home": mock_home,
        "workspace": workspace,
        "install_dir": install.INSTALL_DIR
    }
    
    # Cleanup
    if orig_home:
        os.environ["HOME"] = orig_home
    
    # CRITICAL: Clean up env vars to avoid leaking to other tests
    for key in ["DECKARD_WORKSPACE_ROOT", "DECKARD_INSTALL_SOURCE", "DECKARD_NO_INTERACTIVE"]:
        if key in os.environ:
            del os.environ[key]
            
    install.INSTALL_DIR = orig_install_dir

def run_mcp_command(command_str, workspace_root):
    """Simulate an MCP client calling the 'command' from the config."""
    # The command_str might have paths. We split it safely.
    import shlex
    cmd_parts = shlex.split(command_str)

    if cmd_parts and cmd_parts[0] == "deckard":
        cmd_parts = [sys.executable, "-m", "deckard"]
    
    # Preserve legacy --workspace-root if present, but avoid injecting roots by default.
    
    # Run the process
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    
    # Use stdio for MCP
    proc = subprocess.Popen(
        cmd_parts,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        bufsize=1
    )
    
    return proc

def send_mcp_request(proc, request):
    """Send JSON-RPC request and wait for response."""
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    
    # Read response
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line)

def parse_pack_metrics(text: str) -> dict:
    metrics = {}
    for line in text.splitlines():
        if line.startswith("m:"):
            _, rest = line.split("m:", 1)
            if "=" in rest:
                k, v = rest.split("=", 1)
                metrics[k.strip()] = v.strip()
    return metrics

@pytest.mark.allow_subprocess
def test_full_cli_mcp_cycle_codex_and_gemini(test_env):
    """
    E2E: Actual Install -> Config Check -> MCP Handshake -> Tool Execute -> Uninstall.
    """
    workspace = test_env["workspace"]
    
    # 1. INSTALL
    print("\n[E2E] Running installation...")
    args = type('Args', (), {'yes': True, 'quiet': True, 'json': False, 'verbose': False, 'update': False})()
    install.do_install(args)
    
    assert test_env["install_dir"].exists(), "Installation directory not created"
    assert (test_env["install_dir"] / "bootstrap.sh").exists(), "bootstrap.sh missing after install"
    assert not (test_env["install_dir"] / "tests").exists(), "tests/ directory should be removed after install"
    
    # 2. VERIFY CONFIGS
    codex_cfg_path = workspace / ".codex" / "config.toml"
    gemini_cfg_path = workspace / ".gemini" / "config.toml"
    
    assert codex_cfg_path.exists(), "Codex config missing"
    assert gemini_cfg_path.exists(), "Gemini config missing"
    
    # 3. VERIFY MCP INTEGRATION (actual handshake)
    # Match command from Gemini config
    cmd_from_cfg = None
    content = gemini_cfg_path.read_text()
    import re
    match = re.search(r'command\s*=\s*"(.*)"', content)
    if match:
        cmd_from_cfg = match.group(1)
    
    assert cmd_from_cfg, f"Could not find 'command' in {gemini_cfg_path}"

    print(f"[E2E] Starting MCP via: {cmd_from_cfg}")
    mcp_proc = run_mcp_command(cmd_from_cfg, workspace)
    
    try:
        # Step A: Initialize Handshake
        init_req = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestClient", "version": "1.0"}
            }
        }
        resp = send_mcp_request(mcp_proc, init_req)
        assert resp and "result" in resp, "MCP Initialize failed"

        # Step B: Force a synchronous scan once for determinism
        scan_req = {
            "jsonrpc": "2.0",
            "id": "1.5",
            "method": "tools/call",
            "params": {
                "name": "scan_once",
                "arguments": {}
            }
        }
        resp = send_mcp_request(mcp_proc, scan_req)
        assert resp and "result" in resp, "Tool 'scan_once' call failed"
        scan_text = resp["result"]["content"][0]["text"]
        assert "PACK1 tool=scan_once ok=true" in scan_text
        scan_metrics = parse_pack_metrics(scan_text)
        assert int(scan_metrics.get("scanned_files", "0")) >= 0
        
        # Step C: Call 'status' tool
        status_req = {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {
                "name": "status",
                "arguments": {}
            }
        }
        resp = send_mcp_request(mcp_proc, status_req)
        assert resp and "result" in resp, "Tool 'status' call failed"
        content_text = resp["result"]["content"][0]["text"]
        # PACK1 default: expect header + index_ready metric
        assert "PACK1 tool=status ok=true" in content_text
        assert "m:index_ready=true" in content_text.lower() or "active" in content_text.lower()
        
    finally:
        # Cleanup MCP process
        mcp_proc.terminate()
        mcp_proc.wait(timeout=5)

    # 4. UNINSTALL
    print("[E2E] Running uninstallation...")
    uninstall_args = type('Args', (), {'uninstall': True, 'yes': True, 'quiet': True, 'json': False, 'verbose': False})()
    install.do_uninstall(uninstall_args)
    
    # 5. VERIFY CLEANUP
    assert not test_env["install_dir"].exists(), "Installation directory still exists after uninstall"
    # Note: Global configs are cleaned in HOME, workspace configs are also cleaned if in CWD.
    # install.py: _remove_mcp_config(Path.cwd() / ".codex" / "config.toml")
    # Our workspace is the CWD for the commands.
    
    # We need to ensure we run uninstall in the same CWD as install
    env = os.environ.copy()
    subprocess.run([sys.executable, str(PROJECT_ROOT / "install.py"), "--uninstall", "-y"], cwd=str(workspace), env=env, check=True)

    def block_gone(p):
        return "[mcp_servers.deckard]" not in p.read_text()

    assert block_gone(codex_cfg_path), "Codex config still contains Deckard block"
    assert block_gone(gemini_cfg_path), "Gemini config still contains Deckard block"
    print("[E2E] All cycles PASSED!")
