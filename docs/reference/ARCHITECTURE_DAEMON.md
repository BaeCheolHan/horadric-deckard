# Daemon Architecture

## Purpose
The daemon is responsible for all background ingestion tasks:
- file watching
- scanning
- parsing
- index writes (SQLite + Tantivy)

It must stay stable under load and never block the HTTP/MCP request loop.

## Responsibilities
- Own the Indexer lifecycle
- Own DB write transactions
- Own embedded search index writes
- Accept commands from HTTP layer (start/stop/rescan)

## Non-Responsibilities
- HTTP routing
- MCP JSON-RPC handling
- Client request formatting

## Execution Model
- Single daemon instance per machine (global DB/index)
- Worker pool for parsing + document creation
- Dedicated DB writer thread

## Interfaces (Target)
- Control channel from HTTP server (start/stop/rescan/status)
- Optional IPC for search queries (read-only)

## Data Paths
- DB: `~/.local/share/sari/index.db`
- Engine index: `~/.local/share/sari/index/global` (policy-dependent)
- Config: `~/.config/sari/config.json`, `<workspace>/.sari/config.json`

## Failure Handling
- Watcher restart on observer death
- Read-priority throttle when search pressure is detected
- Batch write rollback on error
