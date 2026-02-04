#!/usr/bin/env python3
"""
Sari Universal Installer/Uninstaller
- Install: pip install sari
- Uninstall: removes files, cleans configs
- Features: Interactive/JSON/Quiet modes, Network Diagnostics
"""
import argparse
import os
import sys
import json
import shutil
from typing import Optional
import subprocess
import signal
import time
import socket
from pathlib import Path

IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))) / "sari"
else:
    INSTALL_DIR = Path.home() / ".local" / "share" / "sari"

# Colors
C_BLUE = "\033[1;34m"
C_GREEN = "\033[1;32m"
C_RED = "\033[1;31m"
C_YELLOW = "\033[1;33m"
C_RESET = "\033[0m"

LOG_FILE = Path.cwd() / "install.log"

# Global Config
CONFIG = {
    "quiet": False,
    "verbose": False,
    "json": False
}

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def _print_json(status, msg, data=None):
    if not CONFIG["json"]:
        return
    payload = {"status": status, "message": msg, "timestamp": time.time()}
    if data:
        payload.update(data)
    print(json.dumps(payload))

def print_step(msg):
    log(msg)
    if CONFIG["json"]:
        return
    if not CONFIG["quiet"]:
        print(f"{C_BLUE}[Sari]{C_RESET} {msg}")

def print_success(msg):
    log(f"SUCCESS: {msg}")
    if CONFIG["json"]:
        _print_json("success", msg)
        return
    if not CONFIG["quiet"]:
        print(f"{C_GREEN}[SUCCESS]{C_RESET} {msg}")

def print_error(msg):
    log(f"ERROR: {msg}")
    if CONFIG["json"]:
        _print_json("error", msg)
        return

    print(f"{C_RED}[ERROR]{C_RESET} {msg}")

def print_warn(msg):
    log(f"WARN: {msg}")
    if CONFIG["json"]:
        return
    if not CONFIG["quiet"]:
        print(f"{C_YELLOW}[WARN]{C_RESET} {msg}")

def confirm(question, default=True):
    """Ask a yes/no question via input()."""
    if os.environ.get("DECKARD_NO_INTERACTIVE"):
        return default

    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    prompt = " [Y/n] " if default else " [y/N] "
    if default is None: prompt = " [y/n] "

    while True:
        sys.stdout.write(question + prompt)
        sys.stdout.flush()
        choice = input().lower()
        if default is not None and choice == "":
            return default
        if choice in valid:
            return valid[choice]
        sys.stdout.write("Please respond with 'yes' or 'no'.\n")

def _create_bootstrap_script(install_dir: Path):
    """Create a bootstrap script that runs 'python -m sari'."""
    if IS_WINDOWS:
        script_path = install_dir / "bootstrap.bat"
        content = (
            "@echo off\r\n"
            "REM Sari Bootstrap Script (Windows)\r\n"
            "REM Auto-update logic can be added here if needed\r\n"
            f'\"{sys.executable}\" -m sari %*\r\n'
        )
    else:
        script_path = install_dir / "bootstrap.sh"
        content = (
            "#!/bin/bash\n"
            "# Sari Bootstrap Script\n"
            "# Starts the server in Proxy Mode (stdio <-> Daemon)\n\n"
            "# Optional: Auto-update on start\n"
            "# python3 -m pip install --upgrade sari >/dev/null 2>&1 &\n\n"
            "exec python3 -m sari \"$@\"\n"
        )

    script_path.write_text(content, encoding="utf-8")
    if not IS_WINDOWS:
        os.chmod(script_path, 0o755)

    print_step(f"Created bootstrap script: {script_path}")
    return script_path

def do_install(args):
    # Part 1: Handle global installation/update
    perform_global_install = False
    bootstrap_name = "bootstrap.bat" if IS_WINDOWS else "bootstrap.sh"

    if args.update:
        if not args.yes and not confirm(f"Sari will be updated. This will replace the contents of {INSTALL_DIR}. Continue?", default=True):
            print_step("Update cancelled. Workspace will still be configured.")
        else:
            print_step("Updating Sari...")
            perform_global_install = True
    elif not INSTALL_DIR.exists() or not (INSTALL_DIR / bootstrap_name).exists():
        print_step("Sari not found or corrupted. Starting installation...")
        perform_global_install = True
    else:
        print_step("Sari is already installed globally. Skipping global installation.")
        print_warn("Use the --update flag to force a re-installation/update.")

    if perform_global_install:
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Install via Pip
        # Check if we are running inside the sari repository itself
        is_repo = (Path.cwd() / "pyproject.toml").exists() and (Path.cwd() / "sari").exists()

        if is_repo:
            print_step("Detected Sari repository. Installing in editable mode...")
            pip_cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
        else:
            print_step("Installing 'sari' package via pip...")
            pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "sari"]

        try:
            subprocess.run(
                pip_cmd,
                check=True,
                capture_output=CONFIG["quiet"]
            )
        except subprocess.CalledProcessError as e:
            print_error(f"Pip install failed: {e}")
            if e.stderr:
                print_error(f"Pip error output: {e.stderr.decode('utf-8', errors='replace')}")
            sys.exit(1)

        # 2. Create Bootstrap Script
        _create_bootstrap_script(INSTALL_DIR)

        # 3. Create Version File (from installed package)
        try:
            ver_res = subprocess.run(
                [sys.executable, "-c", "import sari.version; print(sari.version.__version__)"],
                capture_output=True, text=True
            )
            if ver_res.returncode == 0:
                (INSTALL_DIR / "VERSION").write_text(ver_res.stdout.strip() + "\n", encoding="utf-8")
        except Exception:
            pass

        print_success("Global installation/update complete!")

    # Part 2: print manual config instructions (no auto config writes)
    print_step("Manual MCP config required (no auto-write).")

    if IS_WINDOWS:
        print_success("Add this block to your MCP config (Windows):")
        print(
            "\n"
            "command = \"powershell\"\n"
            "args = [\"-NoProfile\", \"-ExecutionPolicy\", \"Bypass\", \"-Command\", \"irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y; & $env:LOCALAPPDATA\\sari\\bootstrap.bat --transport stdio\"]\n"
        )
    else:
        print_success("Add this block to your MCP config (macOS/Linux):")
        bash_cmd = (
            "export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin && "
            "(curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y || true) && "
            "exec ~/.local/share/sari/bootstrap.sh --transport stdio"
        )
        print(
            "\n"
            "[mcp_servers.sari]\n"
            "command = \"bash\"\n"
            f"args = [\"-lc\", \"{bash_cmd}\"]\n"
        )

def do_uninstall(args):
    def _schedule_remove(path: Path):
        """Remove install dir after this process exits (self-uninstall safe)."""
        try:
            cmd = [
                sys.executable,
                "-c",
                (
                    "import time,shutil,os; "
                    "time.sleep(1); "
                    "shutil.rmtree(os.path.expanduser(r'%s'), ignore_errors=True)"
                ) % str(path),
            ]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print_warn(f"Failed to schedule uninstall cleanup: {e}")

    if not INSTALL_DIR.exists():
        print_warn("Sari is not installed.")

    if not args.yes and not confirm("Uninstall Sari? (Deletes DB & Configs)", default=False):
        return

    # 1. Pip Uninstall
    print_step("Uninstalling 'sari' package via pip...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", "sari"],
            check=False,
            capture_output=CONFIG["quiet"]
        )
    except Exception:
        pass

    # 2. Remove Data Directory
    if INSTALL_DIR.exists():
        print_step(f"Removing {INSTALL_DIR}...")
        try:
            running_from_install = Path(__file__).resolve().parent == INSTALL_DIR
            if running_from_install:
                _schedule_remove(INSTALL_DIR)
            else:
                shutil.rmtree(INSTALL_DIR)
        except Exception as e:
            print_warn(f"Failed to remove install dir: {e}")

    print_success("Uninstallation Complete.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uninstall", action="store_true", help="Uninstall")
    parser.add_argument("--update", action="store_true", help="Force update of existing installation")
    parser.add_argument("-y", "--yes", "--no-interactive", action="store_true", help="Skip prompts")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose")

    args = parser.parse_args()
    CONFIG["quiet"] = args.quiet
    CONFIG["json"] = args.json
    CONFIG["verbose"] = args.verbose

    if args.yes or args.quiet or args.json:
        os.environ["DECKARD_NO_INTERACTIVE"] = "1"
        args.yes = True

    try:
        if args.uninstall: do_uninstall(args)
        else: do_install(args)
    except KeyboardInterrupt:
        if not args.quiet: print("\n[Aborted]")
        sys.exit(1)

if __name__ == "__main__":
    main()