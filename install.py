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

def main():
    print_step("Starting Deckard installation...")

    # 1. Clone Repo
    if INSTALL_DIR.exists():
        print_step(f"Directory {INSTALL_DIR} exists. Updating...")
        try:
            subprocess.run(["git", "-C", str(INSTALL_DIR), "pull"], check=True)
        except subprocess.CalledProcessError:
            print_error("Failed to update git repo.")
    else:
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

    # Stop running daemon to ensure update application
    print_step("Stopping any running Deckard daemon...")
    try:
        subprocess.run([str(bootstrap_script), "daemon", "stop"], 
                       stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       timeout=5)
    except Exception:
        pass

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
