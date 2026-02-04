#!/bin/bash
# Sari MCP Bootstrap Script
# Starts the server in Proxy Mode (stdio <-> Daemon)

# Resolve script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$DIR"
INSTALL_DIR="$HOME/.local/share/sari"

# Uninstall helper (explicit command)
if [ "$1" = "uninstall" ]; then
    echo "[sari] uninstall: stopping daemon and removing install dir" >&2
    if [ -x "$INSTALL_DIR/bootstrap.sh" ]; then
        "$INSTALL_DIR/bootstrap.sh" daemon stop >/dev/null 2>&1 || true
    fi
    # Remove install dir
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
    fi
    # Remove sari block from codex configs (project/global)
    python3 - <<'PY'
from pathlib import Path
def strip_sari(cfg: Path):
    if not cfg.exists():
        return
    lines = cfg.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_sari = False
    for line in lines:
        if line.strip() == "[mcp_servers.sari]":
            in_sari = True
            continue
        if in_sari and line.startswith("[") and line.strip() != "[mcp_servers.sari]":
            in_sari = False
            new_lines.append(line)
            continue
        if not in_sari:
            new_lines.append(line)
    cfg.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

home = Path.home()
strip_sari(home / ".codex" / "config.toml")
strip_sari(home / ".gemini" / "config.toml")
cwd = Path.cwd()
strip_sari(cwd / ".codex" / "config.toml")
strip_sari(cwd / ".gemini" / "config.toml")
PY
    echo "[sari] uninstall: done" >&2
    exit 0
fi

# Self-install/update: Disabled to prioritize local development
# Use install.py manually if a global installation is needed.
if [ "${DECKARD_SKIP_INSTALL:-}" != "1" ]; then
    # Skip if --skip-install is present in args
    for arg in "$@"; do
        if [ "$arg" = "--skip-install" ]; then
            export DECKARD_SKIP_INSTALL=1
            break
        fi
    done
fi

# Add repo root to PYTHONPATH
export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"

# Inject Version from package metadata if available
if command -v python3 >/dev/null 2>&1; then
    VERSION=$(
        python3 - <<'PY'
try:
    from sari.version import __version__
    print(__version__)
except Exception:
    pass
PY
    )
    if [ -n "$VERSION" ]; then
        export SARI_VERSION="$VERSION"
    fi
fi

# Optional: accept workspace root via args and map to env for MCP.
# Usage: bootstrap.sh --workspace-root /path [other args...]
if [ $# -gt 0 ]; then
    while [ $# -gt 0 ]; do
        case "$1" in
            --workspace-root)
                shift
                if [ -n "$1" ]; then
                    export DECKARD_WORKSPACE_ROOT="$1"
                    shift
                else
                    echo "[sari] ERROR: --workspace-root requires a path" >&2
                    exit 2
                fi
                ;;
            --workspace-root=*)
                export DECKARD_WORKSPACE_ROOT="${1#*=}"
                shift
                ;;
            --skip-install)
                export DECKARD_SKIP_INSTALL=1
                shift
                ;;
            *)
                break
                ;;
        esac
    done
fi

# Announce version to stderr (visible in host logs/console)
echo "[Sari] Starting (v${SARI_VERSION:-dev})..." >&2

# Run Sari (No more Deckard fallback)
if [ $# -eq 0 ]; then
    exec python3 -m sari
else
    exec python3 -m sari "$@"
fi
