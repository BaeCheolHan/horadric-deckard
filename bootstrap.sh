#!/bin/bash
# Sari MCP Bootstrap Script
# Starts the server in Proxy Mode (stdio <-> Daemon)

# Resolve script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$DIR"
if [ -n "$XDG_DATA_HOME" ]; then
    INSTALL_DIR="$XDG_DATA_HOME/sari"
else
    INSTALL_DIR="$HOME/.local/share/sari"
fi

# Uninstall helper (explicit command)
if [ "$1" = "uninstall" ]; then
    echo "[sari] uninstall: removing install, DB, configs, caches" >&2
    if command -v python3 >/dev/null 2>&1 && [ -f "$ROOT_DIR/install.py" ]; then
        python3 "$ROOT_DIR/install.py" --uninstall --no-interactive >/dev/null 2>&1 || true
    else
        if command -v python3 >/dev/null 2>&1; then
            python3 -m sari --cmd uninstall --no-interactive >/dev/null 2>&1 || true
        else
            if [ -x "$INSTALL_DIR/bootstrap.sh" ]; then
                "$INSTALL_DIR/bootstrap.sh" daemon stop >/dev/null 2>&1 || true
            fi
            if [ -d "$INSTALL_DIR" ]; then
                rm -rf "$INSTALL_DIR"
            fi
        fi
    fi
    echo "[sari] uninstall: done. Please manually remove [mcp_servers.sari] from your config files." >&2
    exit 0
fi


# Self-install/update: Disabled to prioritize local development
# Use install.py manually if a global installation is needed.
# Self-install/update: Disabled to prioritize local development
# Use install.py manually if a global installation is needed.
# PRIORITY: SARI_
SKIP_INSTALL="${SARI_SKIP_INSTALL:-}"
if [ "$SKIP_INSTALL" != "1" ]; then
    # Skip if --skip-install is present in args
    for arg in "$@"; do
        if [ "$arg" = "--skip-install" ]; then
            export SARI_SKIP_INSTALL=1
            break
        fi
    done
fi

# ... (omitted) ...

# Optional: accept workspace root via args and map to env for MCP.
# Usage: bootstrap.sh --workspace-root /path [other args...]
if [ $# -gt 0 ]; then
    while [ $# -gt 0 ]; do
        case "$1" in
            --workspace-root)
                shift
                if [ -n "$1" ]; then
                    export SARI_WORKSPACE_ROOT="$1"
                    shift
                else
                    echo "[sari] ERROR: --workspace-root requires a path" >&2
                    exit 2
                fi
                ;;
            --workspace-root=*)
                export SARI_WORKSPACE_ROOT="${1#*=}"
                shift
                ;;
            --skip-install)
                export SARI_SKIP_INSTALL=1
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

# Run Sari
if [ $# -eq 0 ]; then
    exec python3 -m sari
else
    exec python3 -m sari "$@"
fi
