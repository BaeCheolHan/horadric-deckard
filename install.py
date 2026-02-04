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
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        INSTALL_DIR = Path(xdg_data) / "sari"
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

def print_success(msg, data=None):
    log(f"SUCCESS: {msg}")
    if CONFIG["json"]:
        _print_json("success", msg, data)
        return
    if not CONFIG["quiet"]:
        print(f"{C_GREEN}[SUCCESS]{C_RESET} {msg}")

def print_error(msg):
    log(f"ERROR: {msg}")
    if CONFIG["json"]:
        _print_json("error", msg)
        return

    # Always print error to stderr, even in quiet mode
    print(f"{C_RED}[ERROR]{C_RESET} {msg}", file=sys.stderr)

def print_warn(msg):
    log(f"WARN: {msg}")
    if CONFIG["json"]:
        return
    if not CONFIG["quiet"]:
        print(f"{C_YELLOW}[WARN]{C_RESET} {msg}")

def confirm(question, default=True):
    """Ask a yes/no question via input()."""
    # Non-interactive mode force (env var)
    if os.environ.get("SARI_NO_INTERACTIVE") == "1":
        return True

    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    prompt = " [Y/n] " if default else " [y/N] "
    if default is None: prompt = " [y/n] "

    while True:
        sys.stdout.write(question + prompt)
        sys.stdout.flush()
        try:
            choice = input().lower()
        except EOFError:
            return default
        if default is not None and choice == "":
            return default
        if choice in valid:
            return valid[choice]
        sys.stdout.write("Please respond with 'yes' or 'no'.\n")

# ... (omitted) ...

    def _remove_custom_config():
        if not args.force_config:
            return
        # Check SARI_CONFIG first
        for env_key in ["SARI_CONFIG"]:
            val = (os.environ.get(env_key) or "").strip()
            if not val:
                continue
            cfg_path = Path(os.path.expanduser(val))
            _safe_unlink(cfg_path)
            # If the config file lives in a sari-named dir, remove that dir too.
            if cfg_path.parent.name.lower() == "sari":
                _safe_unlink(cfg_path.parent)

    def _remove_workspace_cache():
        ws_root = (
            (args.workspace_root or "").strip()
            or (os.environ.get("SARI_WORKSPACE_ROOT") or "").strip()
            or (os.environ.get("SARI_WORKSPACE_ROOT") or "").strip()
        )
        if not ws_root:
            return
        root = Path(os.path.expanduser(ws_root))
# ... (omitted) ...

    if args.yes or args.quiet or args.json:
        os.environ["SARI_NO_INTERACTIVE"] = "1"
        args.yes = True
    elif not sys.stdin.isatty():
        os.environ["SARI_NO_INTERACTIVE"] = "1"
        args.yes = True

def _create_bootstrap_script(install_dir: Path):
    """Create a bootstrap script that runs 'python -m sari.main'."""
    if IS_WINDOWS:
        script_path = install_dir / "bootstrap.bat"
        py = sys.executable
        content = (
            "@echo off\r\n"
            "REM Sari Bootstrap Script (Windows)\r\n"
            "REM Auto-update logic can be added here if needed\r\n"
            "REM Uninstall helper\r\n"
            "if \"%~1\"==\"uninstall\" (\r\n"
            "  if exist \"%~dp0install.py\" (\r\n"
            f"    \"{py}\" \"%~dp0install.py\" --uninstall --no-interactive\r\n"
            "  ) else (\r\n"
            f"    \"{py}\" -m sari.main --cmd uninstall --no-interactive\r\n"
            "  )\r\n"
            "  exit /b 0\r\n"
            ")\r\n"
            f"\"{py}\" -m sari.mcp.cli daemon start -d\r\n"
            f"\"{py}\" -m sari.main %*\r\n"
        )
    else:
        script_path = install_dir / "bootstrap.sh"
        content = (
            "#!/bin/bash\n"
            "# Sari Bootstrap Script\n"
            "# Starts the server in Proxy Mode (stdio <-> Daemon)\n\n"
            "# Optional: Auto-update on start\n"
            "# python3 -m pip install --upgrade sari >/dev/null 2>&1 &\n\n"
            "# Uninstall helper\n"
            "if [ \"$1\" = \"uninstall\" ]; then\n"
            "  if [ -f \"$0\" ]; then\n"
            "    DIR=\"$( cd \"$( dirname \"${BASH_SOURCE[0]}\" )\" && pwd )\"\n"
            "  else\n"
            "    DIR=\"$(pwd)\"\n"
            "  fi\n"
            "  if [ -f \"$DIR/install.py\" ]; then\n"
            "    python3 \"$DIR/install.py\" --uninstall --no-interactive >/dev/null 2>&1 || true\n"
            "  else\n"
            "    python3 -m sari.main --cmd uninstall --no-interactive >/dev/null 2>&1 || true\n"
            "  fi\n"
            "  exit 0\n"
            "fi\n\n"
            "python3 -m sari.mcp.cli daemon start -d >/dev/null 2>&1 || true\n"
            "exec python3 -m sari.main \"$@\"\n"
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
    install_source = (os.environ.get("SARI_INSTALL_SOURCE") or "").strip()

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

        if args.update and INSTALL_DIR.exists():
            try:
                shutil.rmtree(INSTALL_DIR)
            except Exception:
                pass
            INSTALL_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Install via Pip
        # Check if we are running inside the sari repository itself
        is_repo = (Path.cwd() / "pyproject.toml").exists() and (Path.cwd() / "sari").exists()

        if install_source:
            pass
        elif is_repo:
            print_step("Detected Sari repository. Installing in editable mode...")
            pip_cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
        else:
            print_step("Installing 'sari' package via pip...")
            pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "sari"]

        should_skip = os.environ.get("SARI_SKIP_INSTALL") == "1"
        if should_skip:
            print_warn("Skipping pip install (SARI_SKIP_INSTALL=1)")
        elif install_source:
            print_step("Using SARI_INSTALL_SOURCE (local/clone) - skipping pip install.")
        else:
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

        # 2. Optional: install from source (copy or clone)
        if install_source:
            source_path = install_source
            if source_path.startswith("file://"):
                source_path = source_path[7:]
            src = Path(os.path.expanduser(source_path))
            copied = False

            def _copy_from(src_dir: Path):
                def _ignore(_, names):
                    skip = {".git", ".idea", ".vscode", "__pycache__", ".pytest_cache", ".mypy_cache", "htmlcov"}
                    return {n for n in names if n in skip}
                shutil.copytree(src_dir, INSTALL_DIR, dirs_exist_ok=True, ignore=_ignore)

            if src.exists():
                _copy_from(src)
                copied = True
            else:
                tmp_dir = None
                try:
                    import tempfile
                    tmp_dir = Path(tempfile.mkdtemp())
                    subprocess.run(["git", "clone", install_source, str(tmp_dir)], check=True, capture_output=CONFIG["quiet"])
                    _copy_from(tmp_dir)
                    copied = True
                except Exception:
                    pass
                finally:
                    if tmp_dir and tmp_dir.exists():
                        shutil.rmtree(tmp_dir, ignore_errors=True)

            if not copied and is_repo:
                _copy_from(Path.cwd())

        # 3. Create Bootstrap Script
        _create_bootstrap_script(INSTALL_DIR)

        # 4. Create Version File (from installed package)
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
            "exec ~/.local/share/sari/bootstrap.sh auto"
        )
        print(
            "\n"
            "[mcp_servers.sari]\n"
            "command = \"bash\"\n"
            f"args = [\"-lc\", \"{bash_cmd}\"]\n"
        )

def do_uninstall(args):
    removed_paths = []
    failed_paths = []

    def _record_result(path: Path, ok: bool):
        if ok:
            removed_paths.append(str(path))
        else:
            failed_paths.append(str(path))

    def _safe_unlink(path: Path):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                return True
            _record_result(path, True)
            return True
        except Exception as e:
            _record_result(path, False)
            print_warn(f"Failed to remove {path}: {e}")
            return False
        return True

    def _default_config_dir() -> Path:
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))) / "sari"
        return Path.home() / ".config" / "sari"

    def _remove_custom_config():
        if not args.force_config:
            return
        for env_key in ["SARI_CONFIG"]:
            val = (os.environ.get(env_key) or "").strip()
            if not val:
                continue
            cfg_path = Path(os.path.expanduser(val))
            _safe_unlink(cfg_path)
            # If the config file lives in a sari-named dir, remove that dir too.
            if cfg_path.parent.name.lower() == "sari":
                _safe_unlink(cfg_path.parent)

    def _remove_workspace_cache():
        ws_root = (
            (args.workspace_root or "").strip()
            or (os.environ.get("SARI_WORKSPACE_ROOT") or "").strip()
        )
        if not ws_root:
            return
        root = Path(os.path.expanduser(ws_root))
        candidates = [
            root / ".codex" / "tools" / "sari",
            root / ".codex" / "tools" / "SARI",
        ]
        for cand in candidates:
            if cand.exists():
                _safe_unlink(cand)

    def _scan_and_remove_workspace_caches():
        home_dir = Path.home()
        max_dirs = 5000
        scanned = 0
        for root, dirnames, _ in os.walk(home_dir):
            scanned += 1
            if scanned > max_dirs:
                print_warn("Workspace cache scan limit reached; some caches may remain.")
                break

            # Skip hidden dirs except .codex
            dirnames[:] = [d for d in dirnames if d == ".codex" or not d.startswith(".")]
            if os.name == "nt":
                dirnames[:] = [d for d in dirnames if d.lower() != "appdata"]
            if ".codex" not in dirnames:
                continue

            codex_dir = Path(root) / ".codex" / "tools"
            for leaf in ["sari", "SARI"]:
                cand = codex_dir / leaf
                if cand.exists():
                    _safe_unlink(cand)

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

    if not args.yes and not confirm("Uninstall Sari? (Deletes DB, configs, caches)", default=False):
        return

    # 0. Stop daemon if running (best effort)
    try:
        subprocess.run(
            [sys.executable, "-m", "sari", "daemon", "stop"],
            check=False,
            capture_output=True
        )
    except Exception:
        pass

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

    # 3. Remove config (default + custom env)
    _remove_custom_config()
    _safe_unlink(_default_config_dir())

    # 4. Remove legacy config dirs (best effort)
    _safe_unlink(Path.home() / ".SARI")

    # 5. Remove workspace-local caches if workspace root is set
    _remove_workspace_cache()
    _scan_and_remove_workspace_caches()

    print_success(
        "Uninstallation Complete.",
        data={"removed": removed_paths, "failed": failed_paths},
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uninstall", action="store_true", help="Uninstall")
    parser.add_argument("--workspace-root", help="Workspace root to remove local caches")
    parser.add_argument("--force-config", action="store_true", help="Remove custom config paths from env")
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
        os.environ["SARI_NO_INTERACTIVE"] = "1"
        args.yes = True
    elif not sys.stdin.isatty():
        os.environ["SARI_NO_INTERACTIVE"] = "1"
        args.yes = True

    try:
        if args.uninstall: do_uninstall(args)
        else: do_install(args)
    except KeyboardInterrupt:
        if not args.quiet: print("\n[Aborted]")
        sys.exit(1)

if __name__ == "__main__":
    main()
