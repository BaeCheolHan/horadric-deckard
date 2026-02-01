#!/usr/bin/env python3
"""
Deckard Automated Installer
- Clones Deckard to ~/.local/share/horadric-deckard
- Configures Claude Desktop automatically
"""
import os
import sys
import json
import shutil
import subprocess
import signal
from pathlib import Path

REPO_URL = "https://github.com/BaeCheolHan/horadric-deckard.git"
INSTALL_DIR = Path.home() / ".local" / "share" / "horadric-deckard"
CLAUDE_CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Claude"
CLAUDE_CONFIG_FILE = CLAUDE_CONFIG_DIR / "claude_desktop_config.json"

def print_step(msg):
    print(f"\\033[1;34m[Deckard Install]\\033[0m {msg}")

def print_success(msg):
    print(f"\\033[1;32m[SUCCESS]\\033[0m {msg}")

def print_error(msg):
    print(f"\\033[1;31m[ERROR]\\033[0m {msg}")

def _run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)

def _list_deckard_pids():
    """Best-effort process scan to find deckard-related daemons."""
    try:
        ps = _run(["ps", "-ax", "-o", "pid=", "-o", "command="], capture_output=True, text=True, check=False)
    except Exception:
        return []
    pids = []
    for line in ps.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid_str, cmd = line.split(None, 1)
            pid = int(pid_str)
        except Exception:
            continue
        if "mcp.daemon" in cmd or "horadric-deckard" in cmd or "deckard" in cmd:
            if str(INSTALL_DIR) in cmd or "mcp.daemon" in cmd:
                pids.append(pid)
    return pids

def _terminate_pids(pids):
    if not pids:
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    for pid in pids:
        try:
            os.kill(pid, 0)
        except Exception:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

def _inspect_codex_config():
    cfg = Path.home() / ".codex" / "config.toml"
    if not cfg.exists():
        return None
    try:
        text = cfg.read_text(encoding="utf-8")
    except Exception:
        return None
    cmd_line = None
    in_deckard = False
    for line in text.splitlines():
        if line.strip() == "[mcp_servers.deckard]":
            in_deckard = True
            continue
        if in_deckard and line.startswith("[") and line.strip() != "[mcp_servers.deckard]":
            in_deckard = False
        if in_deckard and line.strip().startswith("command"):
            cmd_line = line.strip()
            break
    return cmd_line

def main():
    print_step("Starting Deckard installation...")

    # 1. Clone Repo (fresh install by default)
    if INSTALL_DIR.exists():
        print_step(f"Directory {INSTALL_DIR} exists. Reinstalling (fresh clone)...")
        try:
            shutil.rmtree(INSTALL_DIR)
        except Exception:
            print_error("Failed to remove existing install directory.")
            sys.exit(1)

    print_step(f"Cloning to {INSTALL_DIR}...")
    try:
        subprocess.run(["git", "clone", REPO_URL, str(INSTALL_DIR)], check=True)
    except subprocess.CalledProcessError:
        print_error("Failed to clone git repo.")
        sys.exit(1)

    # 2. Setup Bootstrap
    bootstrap_script = INSTALL_DIR / "bootstrap.sh"
    if not bootstrap_script.exists():
        print_error("bootstrap.sh not found!")
        sys.exit(1)
    
    os.chmod(bootstrap_script, 0o755)
    print_success("Repository set up successfully.")

    # Remove .git to avoid macOS provenance/permission issues
    git_dir = INSTALL_DIR / ".git"
    if git_dir.exists():
        try:
            shutil.rmtree(git_dir)
            print_step("Removed .git directory (fresh install mode).")
        except Exception:
            print_error("Failed to remove .git directory.")

    # Stop running daemon to ensure update application
    print_step("Stopping any running Deckard daemon...")
    try:
        _run([str(bootstrap_script), "daemon", "stop"],
             stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
             timeout=5)
    except Exception:
        pass

    # Fallback: terminate any lingering deckard daemons
    pids = _list_deckard_pids()
    if pids:
        print_step(f"Found running deckard processes: {pids}. Terminating...")
        _terminate_pids(pids)

    # Inspect codex config to avoid mixed command paths
    cmd_line = _inspect_codex_config()
    if cmd_line:
        print_step(f"Detected deckard command in ~/.codex/config.toml: {cmd_line}")
        if str(bootstrap_script) not in cmd_line:
            print_error("WARNING: Mixed deckard command detected (repo vs install). This can cause protocol mismatch.")
            print("  Recommendation: set command to the install path shown below:")
            print(f"  Command: {bootstrap_script}")

    # 3. Configure Claude Desktop
    if CLAUDE_CONFIG_DIR.exists():
        print_step("Found Claude Desktop configuration.")
        
        config = {}
        if CLAUDE_CONFIG_FILE.exists():
            try:
                with open(CLAUDE_CONFIG_FILE, "r") as f:
                    config = json.load(f)
            except json.JSONDecodeError:
                print_error("Existing config file is invalid JSON. Skipping auto-config.")
                return

        mcp_servers = config.get("mcpServers", {})
        
        # Inject Deckard config
        mcp_servers["deckard"] = {
            "command": str(bootstrap_script),
            "args": [],
            "env": {}
        }
        
        config["mcpServers"] = mcp_servers
        
        # Backup
        if CLAUDE_CONFIG_FILE.exists():
            shutil.copy(CLAUDE_CONFIG_FILE, str(CLAUDE_CONFIG_FILE) + ".bak")
        
        with open(CLAUDE_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
            
        print_success("Added 'deckard' to claude_desktop_config.json")
    else:
        print_step("Claude Desktop not found. Skipping auto-config.")
        print("Manual Config Required:")
        print(f"  Command: {bootstrap_script}")

    print_success("Installation Complete! Restart Claude Desktop to use Deckard.")

if __name__ == "__main__":
    main()
