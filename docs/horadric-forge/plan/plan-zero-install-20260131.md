# Plan: Zero-Install MCP Bootstrapper (v2.6.1)

> **Date**: 2026-01-31
> **Goal**: Evolve from "Archive Distribution" to "Just-in-Time Provisioning" for Local Search Tool.
> **Driven by**: User request for seamless UX ("Install via Config").

## 1. Problem Statement
- Current `install.sh` physically downloads and unzips the tool (`sari`) into the workspace.
- Requires manual re-execution of `install.sh` for updates or new workspaces.
- Users want a "Configuration-only" experience where adding a JSON snippet automatically handles the rest.

## 2. Proposed Solution: The Bootstrapper
Introduce a lightweight shell script (`bootstrap-sari.sh`) that acts as a bridge between the MCP Client (Gemini/Codex) and the actual Python tool.

### Workflow
1.  **MCP Config**: Defines `command` as `/bin/bash bootstrap-sari.sh`.
2.  **Bootstrapper**:
    - Checks if the tool exists in `.codex/tools/local-search` or `~/.cache/horadric/sari`.
    - **IF MISSING**: Downloads the latest Zip from GitHub, extracts it, and sets up the environment.
    - **IF PRESENT**: Validates integrity (optional).
    - **EXEC**: Replaces the current shell process with `python3 server.py`.

## 3. Implementation Details

### A. `horadric-forge/bootstrap-sari.sh`
- **Inputs**: `DECKARD_VERSION` (optional env var).
- **Logic**:
  ```bash
  TARGET_DIR=".codex/tools/local-search"
  if [ ! -f "$TARGET_DIR/mcp/server.py" ]; then
    echo "Provisioning Sari..."
    curl -L "https://github.com/.../v1.0.0.zip" -o sari.zip
    unzip sari.zip ...
  fi
  exec python3 "$TARGET_DIR/mcp/server.py"
  ```

### B. `horadric-forge/install.sh` Refactoring
- **Role Shift**: From "Full Installer" to "Rules Installer & Configurator".
- **Tasks**:
  1.  Install Rules (`.codex/rules`) - Physical copy needed for context.
  2.  **SKIP** Tool physical installation.
  3.  **Inject** Bootstrapper config into `.gemini/settings.json` and `.codex/config.toml`.
      - The config will point to the raw URL of `bootstrap-sari.sh` or a local copy of it.

### C. `manifest.toml` Update
- Add `bootstrap_url` or ensure `tools.local-search.url` is accessible by the bootstrapper.

## 4. Verification Plan (DoD)
1.  **Clean State**: Remove `test-workspace/.codex/tools`.
2.  **Config Setup**: Manually (or via updated install.sh) set `settings.json` to use the bootstrapper.
3.  **Trigger**: Run Gemini or a test script to invoke MCP.
4.  **Expectation**:
    - Bootstrapper log appears ("Provisioning...").
    - Tool is downloaded.
    - MCP server starts and responds to `initialize`.

## 5. Artifacts
- `horadric-forge/bootstrap-sari.sh`
- Modified `horadric-forge/install.sh`
