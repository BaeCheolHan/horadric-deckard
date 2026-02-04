import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


IS_WINDOWS = os.name == "nt"


def _install_dir() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))) / "sari"
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "sari"
    return Path.home() / ".local" / "share" / "sari"


def _default_config_dir() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))) / "sari"
    return Path.home() / ".config" / "sari"


def _confirm(question: str, default: bool) -> bool:
    if not sys.stdin.isatty():
        return default
    prompt = " [Y/n] " if default else " [y/N] "
    while True:
        sys.stdout.write(question + prompt)
        sys.stdout.flush()
        try:
            choice = input().lower()
        except EOFError:
            return default
        if choice == "" and default is not None:
            return default
        if choice in {"yes", "y", "ye"}:
            return True
        if choice in {"no", "n"}:
            return False
        sys.stdout.write("Please respond with 'yes' or 'no'.\n")


def _safe_remove(path: Path, removed: list[str], failed: list[str]) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            return
        removed.append(str(path))
    except Exception:
        failed.append(str(path))


def _remove_custom_config(force_config: bool, removed: list[str], failed: list[str]) -> None:
    if not force_config:
        return
    for env_key in ["SARI_CONFIG"]:
        val = (os.environ.get(env_key) or "").strip()
        if not val:
            continue
        cfg_path = Path(os.path.expanduser(val))
        _safe_remove(cfg_path, removed, failed)
        if cfg_path.parent.name.lower() == "sari":
            _safe_remove(cfg_path.parent, removed, failed)


def _remove_workspace_cache(workspace_root: Optional[str], removed: List[str], failed: List[str]) -> None:
    ws_root = (workspace_root or "").strip()
    if not ws_root:
        ws_root = (
            (os.environ.get("SARI_WORKSPACE_ROOT") or "").strip()
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
            _safe_remove(cand, removed, failed)


def _scan_and_remove_workspace_caches(removed: List[str], failed: List[str]) -> None:
    home_dir = Path.home()
    max_dirs = 5000
    scanned = 0
    for root, dirnames, _ in os.walk(home_dir):
        scanned += 1
        if scanned > max_dirs:
            break
        dirnames[:] = [d for d in dirnames if d == ".codex" or not d.startswith(".")]
        if IS_WINDOWS:
            dirnames[:] = [d for d in dirnames if d.lower() != "appdata"]
        if ".codex" not in dirnames:
            continue
        codex_dir = Path(root) / ".codex" / "tools"
        for leaf in ["sari", "SARI"]:
            cand = codex_dir / leaf
            if cand.exists():
                _safe_remove(cand, removed, failed)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sari --cmd uninstall")
    parser.add_argument("--no-interactive", "-y", action="store_true", help="Skip prompts")
    parser.add_argument("--workspace-root", help="Workspace root to remove local caches")
    parser.add_argument("--force-config", action="store_true", help="Remove custom config paths from env")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    if args.no_interactive:
        os.environ["SARI_NO_INTERACTIVE"] = "1"

    if not args.no_interactive:
        if not sys.stdin.isatty():
            args.no_interactive = True
        else:
            ok = _confirm("Uninstall Sari? (Deletes DB, configs, caches)", default=False)
            if not ok:
                return 0

    removed: List[str] = []
    failed: List[str] = []

    try:
        subprocess.run([sys.executable, "-m", "sari", "daemon", "stop"], check=False, capture_output=True)
    except Exception:
        pass

    try:
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "sari"], check=False, capture_output=True)
    except Exception:
        pass

    _safe_remove(_install_dir(), removed, failed)
    _remove_custom_config(args.force_config, removed, failed)
    _safe_remove(_default_config_dir(), removed, failed)
    _safe_remove(Path.home() / ".SARI", removed, failed)
    _remove_workspace_cache(args.workspace_root, removed, failed)
    _scan_and_remove_workspace_caches(removed, failed)

    if args.json:
        import json

        print(json.dumps({"status": "success", "removed": removed, "failed": failed}))
    else:
        print("[SUCCESS] Uninstallation Complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
