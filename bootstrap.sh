#!/bin/bash
# Deckard MCP Bootstrap Script
# Starts the server in Proxy Mode (stdio <-> Daemon)

# Resolve script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$DIR"
INSTALL_DIR="$HOME/.local/share/horadric-deckard"

# Uninstall helper (explicit command)
if [ "$1" = "uninstall" ]; then
    echo "[deckard] uninstall: stopping daemon and removing install dir" >&2
    if [ -x "$INSTALL_DIR/bootstrap.sh" ]; then
        "$INSTALL_DIR/bootstrap.sh" daemon stop >/dev/null 2>&1 || true
    fi
    # Remove install dir
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
    fi
    # Remove deckard block from codex configs (project/global)
    python3 - <<'PY'
from pathlib import Path
def strip_deckard(cfg: Path):
    if not cfg.exists():
        return
    lines = cfg.read_text(encoding="utf-8").splitlines()
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
    cfg.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

home = Path.home()
strip_deckard(home / ".codex" / "config.toml")
strip_deckard(home / ".gemini" / "config.toml")
cwd = Path.cwd()
strip_deckard(cwd / ".codex" / "config.toml")
strip_deckard(cwd / ".gemini" / "config.toml")
PY
    echo "[deckard] uninstall: done" >&2
    exit 0
fi

# Self-install/update: if running from repo (not install dir), bootstrap install dir first
if [ "${DECKARD_BOOTSTRAP_DONE:-}" != "1" ] && [ "$ROOT_DIR" != "$INSTALL_DIR" ]; then
    # Determine repo version (if available)
    REPO_VERSION=""
    if [ -d "$ROOT_DIR/.git" ] && command -v git >/dev/null 2>&1; then
        REPO_VERSION=$(git -C "$ROOT_DIR" describe --tags --abbrev=0 2>/dev/null)
        REPO_VERSION=${REPO_VERSION#v}
    fi

    INST_VERSION=""
    if [ -f "$INSTALL_DIR/VERSION" ]; then
        INST_VERSION=$(cat "$INSTALL_DIR/VERSION" 2>/dev/null | tr -d '\n')
    fi

    NEED_INSTALL=0
    if [ ! -x "$INSTALL_DIR/bootstrap.sh" ]; then
        NEED_INSTALL=1
    elif [ -n "$REPO_VERSION" ] && [ "$REPO_VERSION" != "$INST_VERSION" ]; then
        NEED_INSTALL=1
    fi

    if [ "$NEED_INSTALL" = "1" ] && [ -f "$ROOT_DIR/install.py" ]; then
        echo "[deckard] bootstrap: installing to $INSTALL_DIR" >&2
        # Redirect stdout to stderr to protect MCP protocol, but show errors
        DECKARD_BOOTSTRAP_DONE=1 python3 "$ROOT_DIR/install.py" --no-interactive 1>&2
        if [ $? -ne 0 ]; then
             echo "[deckard] bootstrap: installation failed. Check install.log." >&2
             # Don't swallow error, exit
             exit 1
        fi
    fi

    if [ -x "$INSTALL_DIR/bootstrap.sh" ]; then
        exec "$INSTALL_DIR/bootstrap.sh" "$@"
    fi
fi

# Add repo root to PYTHONPATH
export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"

# Inject Version from Git or File
if [ -d "$ROOT_DIR/.git" ] && command -v git >/dev/null 2>&1; then
    VERSION=$(git -C "$ROOT_DIR" describe --tags --abbrev=0 2>/dev/null)
    # If standard tag format (v1.2.3), strip 'v' if preferred, or keep it. 
    # server.py expects string. Let's keep it as is (v1.1.0) or strip? 
    # Most python libs use 1.1.0. 
    if [ -n "$VERSION" ]; then
        # Strip leading 'v'
        export DECKARD_VERSION="${VERSION#v}"
    fi
elif [ -f "$ROOT_DIR/VERSION" ]; then
    export DECKARD_VERSION="$(cat "$ROOT_DIR/VERSION" | tr -d '\n')"
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
                    echo "[deckard] ERROR: --workspace-root requires a path" >&2
                    exit 2
                fi
                ;;
            --workspace-root=*)
                export DECKARD_WORKSPACE_ROOT="${1#*=}"
                shift
                ;;
            *)
                break
                ;;
        esac
    done
fi

# Announce version to stderr (visible in host logs/console)
echo "[Deckard] Starting Daemon (v${DECKARD_VERSION:-dev})..." >&2

# Run CLI (default to auto mode if no args)
if [ $# -eq 0 ]; then
    exec python3 -m mcp.cli auto
else
    exec python3 -m mcp.cli "$@"
fi
