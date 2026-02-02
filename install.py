#!/usr/bin/env python3
"""
Deckard Universal Installer/Uninstaller (v2.7.0)
- Install: clones repo, configures Claude/Codex
- Uninstall: removes files, cleans configs
- Features: Interactive/JSON/Quiet modes, Network Diagnostics
"""
import argparse
import os
import sys
import json
import shutil
import subprocess
import signal
import time
from pathlib import Path

IS_WINDOWS = os.name == 'nt'
REPO_URL = "https://github.com/BaeCheolHan/horadric-deckard.git"

if IS_WINDOWS:
    INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))) / "horadric-deckard"
    CLAUDE_CONFIG_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))) / "Claude"
else:
    INSTALL_DIR = Path.home() / ".local" / "share" / "horadric-deckard"
    CLAUDE_CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Claude"

REPO_ROOT = Path(__file__).resolve().parent
CLAUDE_CONFIG_FILE = CLAUDE_CONFIG_DIR / "claude_desktop_config.json"

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
    if CONFIG["json"]: return
    if not CONFIG["quiet"]:
        print(f"{C_BLUE}[Deckard]{C_RESET} {msg}")

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
    
    # Shield Item 3: Smart Guide for Network/Permissions
    lower_msg = msg.lower()
    if "resolve host" in lower_msg or "temporary failure" in lower_msg or "connect" in lower_msg or "clone" in lower_msg:
        print_warn("Network Error Detected!")
        print(f"{C_YELLOW}  -> Check your internet connection.{C_RESET}")
        print(f"{C_YELLOW}  -> If behind corporate proxy, set HTTP_PROXY/HTTPS_PROXY env vars.{C_RESET}")
        print(f"{C_YELLOW}  -> Verify DNS settings.{C_RESET}")
    elif "permission" in lower_msg or "access" in lower_msg:
        print_warn("Permission Error Detected!")
        print(f"{C_YELLOW}  -> Try running with valid permissions (check ~/.local/share ownership).{C_RESET}")

def print_warn(msg):
    log(f"WARN: {msg}")
    if CONFIG["json"]: return
    if not CONFIG["quiet"]:
        print(f"{C_YELLOW}[WARN]{C_RESET} {msg}")

def print_next_steps(version):
    if CONFIG["quiet"] or CONFIG["json"]:
        return
        
    print("\n" + "="*50)
    print(f"{C_GREEN}Deckard v{version} Installed Successfully! 🚀{C_RESET}")
    print("="*50)
    print("Next Steps:")
    print(f"1. {C_BLUE}Restart your Editor{C_RESET} (Claude/Cursor) to load MCP.")
    print(f"2. Check status: {C_YELLOW}deckard status{C_RESET}")
    
    bootstrap_path = INSTALL_DIR / ("bootstrap.bat" if IS_WINDOWS else "bootstrap.sh")
    print(f"3. Run Doctor if issues: {C_YELLOW}{sys.executable} {INSTALL_DIR}/doctor.py{C_RESET}")
    print("="*50 + "\n")

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

def _run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)

def _list_deckard_pids():
    """Best-effort process scan to find deckard-related daemons."""
    pids = []
    if IS_WINDOWS:
        try:
            # Use tasklist to find python processes
            res = _run(["tasklist", "/FO", "CSV", "/V"], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                import csv
                import io
                reader = csv.DictReader(io.StringIO(res.stdout))
                for row in reader:
                    cmdline = row.get("Image Name", "") + " " + row.get("Window Title", "")
                    pid = int(row.get("PID", 0))
                    if "python" in cmdline.lower() and ("mcp.daemon" in cmdline or "deckard" in cmdline.lower()):
                        pids.append(pid)
        except Exception: pass
    else:
        try:
            ps = _run(["ps", "-ax", "-o", "pid=", "-o", "command="], capture_output=True, text=True, check=False)
            for line in ps.stdout.splitlines():
                line = line.strip()
                if not line: continue
                try:
                    pid_str, cmd = line.split(None, 1)
                    pid = int(pid_str)
                except Exception: continue
                if "mcp.daemon" in cmd or "horadric-deckard" in cmd or "deckard" in cmd:
                    if str(INSTALL_DIR) in cmd or "mcp.daemon" in cmd:
                        pids.append(pid)
        except Exception: pass
    return pids

def _terminate_pids(pids):
    if not pids: return
    for pid in pids:
        try:
            if IS_WINDOWS:
                _run(["taskkill", "/F", "/PID", str(pid)], check=False)
            else:
                os.kill(pid, signal.SIGTERM)
        except: pass
    if not IS_WINDOWS:
        time.sleep(1)
        for pid in pids:
            try: os.kill(pid, 0)
            except: continue
            try: os.kill(pid, signal.SIGKILL)
            except: pass

def _resolve_workspace_root():
    for key in ("DECKARD_WORKSPACE_ROOT", "LOCAL_SEARCH_WORKSPACE_ROOT"):
        val = os.environ.get(key, "").strip()
        if val:
            if val == "${cwd}": return str(Path.cwd())
            p = Path(os.path.expanduser(val))
            if p.exists(): return str(p.resolve())
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".codex-root").exists(): return str(parent)
    return str(cwd)

def _upsert_mcp_config(cfg_path: Path, command_path: str, workspace_root: str):
    """Generic MCP server block upsert into TOML config (Codex/Gemini)."""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = cfg_path.read_text(encoding="utf-8").splitlines() if cfg_path.exists() else []
    
    new_lines = []
    in_deckard = False
    for line in lines:
        if line.strip() == "[mcp_servers.deckard]":
            in_deckard = True
            continue
        if in_deckard and line.startswith("[") and line.strip() != "[mcp_servers.deckard]":
            in_deckard = False
            new_lines.append(line)
            continue
        if not in_deckard:
            new_lines.append(line)

    deckard_block = [
        "[mcp_servers.deckard]",
        f"command = \"{command_path}\"",
        f"args = [\"--workspace-root\", \"{workspace_root}\"]",
        f"env = {{ DECKARD_WORKSPACE_ROOT = \"{workspace_root}\" }}",
        "startup_timeout_sec = 60",
    ]

    # Try to insert after model parameters or at the top
    insert_at = 0
    for i, line in enumerate(new_lines):
        if line.startswith("model_reasoning_effort") or line.startswith("model_name"):
            insert_at = i + 1
            break
            
    if insert_at == 0 and not new_lines: new_lines = deckard_block
    elif insert_at == 0: new_lines = deckard_block + new_lines
    else: new_lines = new_lines[:insert_at] + deckard_block + new_lines[insert_at:]
        
    cfg_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print_step(f"Updated Deckard config in {cfg_path}")

def _remove_mcp_config(cfg_path: Path):
    """Generic MCP server block removal from TOML config (Codex/Gemini)."""
    if not cfg_path.exists(): return
    try:
        lines = cfg_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        in_deckard, removed = False, False
        for line in lines:
            if line.strip() == "[mcp_servers.deckard]":
                in_deckard = True
                removed = True
                continue
            if in_deckard and line.startswith("[") and line.strip() != "[mcp_servers.deckard]":
                in_deckard = False
                new_lines.append(line)
                continue
            if not in_deckard:
                new_lines.append(line)
        if removed:
            print_step(f"Removed Deckard config from {cfg_path}")
            cfg_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        print_warn(f"Failed to update {cfg_path}: {e}")

# Backward-compatible aliases (tests/imports rely on old names)
def _upsert_deckard_block(cfg_path: Path, command_path: str, workspace_root: str):
    return _upsert_mcp_config(cfg_path, command_path, workspace_root)

def _remove_deckard_block(cfg_path: Path):
    return _remove_mcp_config(cfg_path)

def do_install(args):
    # Part 1: Handle global installation/update
    perform_global_install = False
    version = "dev"
    if args.update:
        if not args.yes and not confirm(f"Deckard will be updated. This will replace the contents of {INSTALL_DIR}. Continue?", default=True):
            print_step("Update cancelled. Workspace will still be configured.")
        else:
            print_step("Updating Deckard...")
            perform_global_install = True
    elif not INSTALL_DIR.exists():
        print_step("Deckard not found. Starting first-time installation...")
        perform_global_install = True
    else:
        print_step("Deckard is already installed globally. Skipping global installation.")
        print_warn("Use the --update flag to force a re-installation/update.")

    if perform_global_install:
        # Stop any running daemons to prevent file locking issues
        pids = _list_deckard_pids()
        if pids:
            print_step(f"Stopping running deckard processes: {pids}")
            _terminate_pids(pids)

        # Remove previous installation if it exists
        if INSTALL_DIR.exists(follow_symlinks=False):
            print_step(f"Removing existing installation at {INSTALL_DIR}...")
            try:
                if INSTALL_DIR.is_symlink():
                    INSTALL_DIR.unlink()
                else:
                    shutil.rmtree(INSTALL_DIR)
            except Exception as e:
                print_error(f"Failed to remove existing directory: {e}")
                sys.exit(1)        
        # Clone the repository
        source_url = os.environ.get("DECKARD_INSTALL_SOURCE", REPO_URL)
        print_step(f"Cloning latest Deckard from {source_url} to {INSTALL_DIR}...")
        try:
            subprocess.run(["git", "clone", source_url, str(INSTALL_DIR)], check=True, capture_output=CONFIG["quiet"])
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print_error(f"Failed to clone git repo. Make sure 'git' is installed and in your PATH. Error: {e}")
            sys.exit(1)

        # Setup bootstrap script and permissions
        bootstrap_name = "bootstrap.bat" if IS_WINDOWS else "bootstrap.sh"
        bootstrap_script = INSTALL_DIR / bootstrap_name
        
        if not bootstrap_script.exists():
            print_error(f"{bootstrap_name} not found in cloned repo!")
            sys.exit(1)
            
        if not IS_WINDOWS:
            os.chmod(bootstrap_script, 0o755)

        # Generate VERSION file from git tag
        try:
            ver = subprocess.check_output(["git", "-C", str(INSTALL_DIR), "describe", "--tags", "--abbrev=0"], text=True).strip()
            version = ver[1:] if ver.startswith("v") else ver
            (INSTALL_DIR / "VERSION").write_text(version + "\n", encoding="utf-8")
        except Exception:
            pass # version remains 'dev'

        # Remove .git and development artifacts
        for artifact in [".git", "tests"]:
            artifact_dir = INSTALL_DIR / artifact
            if artifact_dir.exists():
                try:
                    shutil.rmtree(artifact_dir)
                    print_step(f"Removed development artifact: {artifact}/")
                except Exception:
                    pass
        
        print_success("Global installation/update complete!")

    # Part 2: ALWAYS configure the local workspace
    print_step("Configuring current workspace...")
    bootstrap_name = "bootstrap.bat" if IS_WINDOWS else "bootstrap.sh"
    bootstrap_script = INSTALL_DIR / bootstrap_name
    if not bootstrap_script.exists():
        print_error(f"Deckard is not installed correctly. Missing {bootstrap_script}.")
        print_error("Please run the installer again with the --update flag.")
        sys.exit(1)

    workspace_root = _resolve_workspace_root()
    mcp_command = str(bootstrap_script)
    
    # Configure workspace-local CLI files
    _upsert_mcp_config(Path(workspace_root) / ".codex" / "config.toml", mcp_command, workspace_root)
    _upsert_mcp_config(Path(workspace_root) / ".gemini" / "config.toml", mcp_command, workspace_root)
    
    # Clean up legacy global configs, just in case
    _remove_mcp_config(Path.home() / ".codex" / "config.toml")
    _remove_mcp_config(Path.home() / ".gemini" / "config.toml")
    
    print_success(f"Workspace '{workspace_root}' is now configured to use Deckard.")

    # Final health check only if we installed/updated something
    if perform_global_install:
        print_step("Running post-install health check (Doctor)...")
        doctor_script = INSTALL_DIR / "doctor.py"
        if doctor_script.exists():
            try:
                env = os.environ.copy()
                env["DECKARD_WORKSPACE_ROOT"] = workspace_root
                subprocess.run([sys.executable, str(doctor_script)], env=env, check=False, capture_output=CONFIG["quiet"])
            except Exception as e:
                print_warn(f"Doctor check failed to run: {e}")
        
        # Only show next steps on a fresh install/update
        try:
            ver_file = INSTALL_DIR / "VERSION"
            if ver_file.exists():
                version = ver_file.read_text().strip()
        except Exception:
            pass
        print_next_steps(version)

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
        print_warn("Deckard is not installed.")
        # Proceed anyway to clean configs
    
    if not args.yes and not confirm("Uninstall Deckard? (Deletes DB)", default=False):
        return

    pids = _list_deckard_pids()
    if pids:
        print_step(f"Stopping daemons: {pids}")
        _terminate_pids(pids)

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
    
    # Clean Codex configs
    _remove_mcp_config(Path.home() / ".codex" / "config.toml")
    _remove_mcp_config(Path.cwd() / ".codex" / "config.toml")
    
    # Clean Gemini configs
    _remove_mcp_config(Path.home() / ".gemini" / "config.toml")
    _remove_mcp_config(Path.cwd() / ".gemini" / "config.toml")

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
        doc_mode = False
        if args.uninstall: do_uninstall(args)
        else: do_install(args)
    except KeyboardInterrupt:
        if not args.quiet: print("\n[Aborted]")
        sys.exit(1)

if __name__ == "__main__":
    main()
