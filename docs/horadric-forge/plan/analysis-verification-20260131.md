# Analysis: Horadric Forge Separation Verification

> **Date**: 2026-01-31
> **Subject**: Verification of the split repositories (`horadric-*`) functionality.
> **Scale**: S1 (Functional Verification & Integration Test)

## 1. Context & Objective
The monolithic `codex-forge` has been split into `horadric-forge` (installer), `horadric-forge-rules` (ruleset), and `sari` (tool).
**Objective**: Verify that the split components work together seamlessly to bootstrap a fully functional AI agent environment in a new workspace.

## 2. Key Verification Points (DoD)
Based on the separation requirements:
1.  **Installation**: Does `install.sh` correctly fetch and place files from separate sources?
2.  **Isolation**: Does `local-search` create its DB in the workspace (`.codex/...`) instead of the user home directory?
3.  **Functionality**: Can the installed `local-search` MCP server actually index files and return search results?
4.  **Safety**: Is the `${cwd}` template string handling robust?

## 3. Analysis of Current State
- **Repositories Created**: `horadric-forge`, `horadric-forge-rules`, `sari`.
- **Installer**: `install.sh` updated to handle local/remote sources.
- **Tool**: `sari` code modified to enforce local DB path.
- **Preliminary Test**: An ad-hoc test script confirmed basic functionality (indexing & search works), but this needs to be formalized.

## 4. Risks & Constraints
- **Python Environment**: The test assumes `python3` is available and has necessary libs. In a real user environment, `pip install` might be needed (dependencies validation).
- **Process Management**: The MCP server runs as a subprocess. Proper termination handling in tests is crucial to avoid zombie processes.

## 5. Proposed Test Strategy
Create a reproducible verification script (`verify_separation.sh`) that:
1.  Cleans up any previous test workspace.
2.  Runs the installer with local path overrides.
3.  Injects dummy content (Java/MD files).
4.  Runs a Python based MCP client harness to assert:
    - Initialization success.
    - DB file creation path.
    - Search result accuracy (expected matches).

## 6. Deliverables
- `docs/codex-forge/plan/plan-verification-20260131.md` (This Plan)
- `tests/verify_separation.sh` (The Verification Script)
- Updated `status-separation-complete-20260131.md` with final verification log.
