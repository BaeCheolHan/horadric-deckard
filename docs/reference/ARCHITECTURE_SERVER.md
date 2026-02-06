# Server Architecture

## Overview
Sari exposes two server surfaces:
- HTTP API server for local search/tool endpoints.
- MCP server for tool-based agent integrations.

Both servers share the same core components:
- `LocalSearchDB` (SQLite)
- `Indexer` (scanner + workers + DB writer)
- `SearchEngine` / embedded Tantivy engine

The HTTP server is the primary runtime entrypoint. MCP is attached and shares the same DB + indexer instance.

## Role Separation (Target)
- **HTTP server**: request/response only (search, read, tool execution).
- **Daemon**: background indexing, file watching, and ingestion only.

This separation avoids blocking requests during heavy indexing and keeps the server responsive.

## Components

### HTTP Server
- Entry: `sari/core/http_server.py`
- Binds to loopback by default.
- Exposes `/search`, `/read`, `/status`, and indexer control endpoints.
- Initializes `BoundHandler` with DB, Indexer, and workspace context.

### MCP Server
- Entry: `sari/mcp/server.py`
- JSON-RPC loop on stdin/stdout.
- Requests are queued and executed on a worker pool to avoid blocking the read loop.
- Uses `WorkspaceRegistry` to lazily create workspace sessions.

### Indexer + Search Engine
- `Indexer` performs scan + watch + parse.
- `DBWriter` batches writes and yields under read pressure.
- Embedded engine (Tantivy) stores a global or per-root index based on policy.

## Concurrency Model
- HTTP server: standard request handling per connection.
- MCP server:
  - stdin read loop enqueues requests.
  - `ThreadPoolExecutor` runs tool execution.
  - stdout writes are synchronized to keep JSON-RPC responses intact.
- Indexer:
  - worker threads for parsing and doc generation.
  - DB writer thread for batched transactions.

## Lifecycle
1. HTTP server starts and binds to loopback.
2. DB initialized.
3. MCP server attached to HTTP runtime.
4. Indexer starts background scan and file watcher.

## Server Data Paths
- DB: `~/.local/share/sari/index.db`
- Engine index: `~/.local/share/sari/index/global` (policy-dependent)
- Config: `~/.config/sari/config.json` and `<workspace>/.sari/config.json`

## Key Policies
- Search-first throttling under load.
- Optional content storage / compression.
- Gitignore-aware scanning (root `.gitignore`).

## Separation Notes
- In a fully separated design, the HTTP server would connect to a daemon-managed DB/indexer via IPC.
- The daemon would be the only process mutating the index, with the HTTP/MCP layer purely read/command.
