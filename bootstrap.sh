#!/bin/bash
# Deckard MCP Bootstrap Script
# Starts the server in Proxy Mode (stdio <-> Daemon)

# Resolve script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$DIR"

# Add repo root to PYTHONPATH
export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"

# Inject Version from Git
if [ -d "$ROOT_DIR/.git" ] && command -v git >/dev/null 2>&1; then
    VERSION=$(git -C "$ROOT_DIR" describe --tags --abbrev=0 2>/dev/null)
    # If standard tag format (v1.2.3), strip 'v' if preferred, or keep it. 
    # server.py expects string. Let's keep it as is (v1.1.0) or strip? 
    # Most python libs use 1.1.0. 
    if [ -n "$VERSION" ]; then
        # Strip leading 'v'
        export DECKARD_VERSION="${VERSION#v}"
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

# Run CLI (default to proxy mode if no args)
if [ $# -eq 0 ]; then
    exec python3 -m mcp.cli proxy
else
    exec python3 -m mcp.cli "$@"
fi
