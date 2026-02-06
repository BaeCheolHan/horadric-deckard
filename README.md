# Sari (사리)

[🇰🇷 한국어 가이드 (Korean Guide)](README_KR.md)

**Sari** is a high-performance **Local Code Search Agent** implementing the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It empowers AI assistants (like Claude, Cursor, Codex) to efficiently navigate, understand, and search large codebases without sending code to external servers.

> **Key Features:**
> - ⚡ **Fast Indexing:** Enterprise-grade Staging & Bulk Merge (1,500+ files/sec).
> - 🧠 **Intelligent Filtering:** Prefix Tree (PathTrie) based overlap detection.
> - 🌐 **Multi-Workspace:** Manage multiple projects with a single high-performance daemon.
> - 🔒 **Low Latency:** Fast Track pipeline for LLM-driven file changes (0.1s freshness).
> - 🩺 **Self-Healing:** Pro Doctor for deep environment diagnostics and repair.

---

## 🚀 Installation & Setup

### Quickstart
1. Install Sari via the high-speed installer:
```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y --update
```

2. Go to your project root and initialize:
```bash
cd /path/to/your/project
sari init
sari daemon start -d
```

---

## ⚙️ Environment Variables (Complete List)

All performance-critical tuning (Debouncing, Framing, Batching) is now **automatically managed** by Sari's adaptive algorithms. Only the following variables remain for environmental control.

### Core Configuration
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_WORKSPACE_ROOT` | Explicitly set the target project root. | (Detected) |
| `SARI_CONFIG` | Override path to `config.json`. | `~/.config/sari/` |
| `SARI_DATA_DIR` | Global directory for SQLite databases. | `~/.local/share/sari/` |
| `SARI_LOG_DIR` | Directory for telemetry and debug logs. | (inside Data Dir) |
| `SARI_REGISTRY_FILE` | Path to the shared server registry. | (inside Config Dir) |

### Scope & Filtering (Additive)
| Variable | Description | Example |
|----------|-------------|---------|
| `SARI_EXCLUDE_DIRS_ADD` | Comma-separated list of directories to ignore. | `secret_dir,temp_cache` |
| `SARI_EXCLUDE_GLOBS_ADD` | Comma-separated list of glob patterns to ignore. | `*.secret,*.tmp` |

### Network & Daemon
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_DAEMON_PORT` | TCP port for the background daemon. | `47779` |
| `SARI_HTTP_API_PORT` | Port for the workspace-specific HTTP API. | `47777` (Auto-increment) |
| `SARI_ALLOW_NON_LOOPBACK` | Allow daemon to bind to 0.0.0.0 (Security risk!). | `0` |

### Engine & Storage
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_ENGINE_MODE` | `embedded` (Tantivy) or `sqlite` (Lightweight). | `embedded` |
| `SARI_ENABLE_FTS` | Enable SQLite Full-Text Search index. | `0` |
| `SARI_STORE_CONTENT_COMPRESS` | Enable zlib compression for stored code. | `0` |
| `SARI_INDEX_WORKERS` | Max parallel workers (Autoscaled based on RAM). | `2` |

### Development & Debugging
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_DEV_JSONL` | Enable JSONL framing for debugging stdio streams. | `0` |
| `SARI_MCP_DEBUG_LOG` | Enable MCP debug traffic log (`mcp_debug.log`) with redaction. | `0` |
| `SARI_ALLOW_LEGACY` | Opt-in legacy fallback for non-namespaced env and legacy root-id acceptance. | `0` |
| `SARI_LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARN`, `ERROR`). | `INFO` |

---

## 🩺 Health & Maintenance

### Sari Doctor (The "Pro" Medic)
Sari includes a deep diagnostic tool to ensure peak performance:
```bash
sari doctor --auto-fix
```
It repairs:
- **Zombie Daemons**: Cleans up stale PID files and orphan processes.
- **DB Integrity**: Validates SQLite page health and index consistency.
- **Registry Repair**: Fixes workspace registration conflicts.

---

## ✅ Required Test Gates

Critical runtime paths (server crash, stdout framing concurrency, dependency drift) must pass dedicated gate tests:

```bash
pytest -m gate -q
```

Local mandatory command (same gate + smoke sequence):

```bash
./scripts/verify-gates.sh
```

Core smoke set:

```bash
pytest -q tests/test_core_main.py tests/test_engines.py tests/test_server.py tests/test_search_engine_mapping.py
```

---

## 🧭 Recent Runtime Changes (1.0.3+)

- **Single integrated DB policy maintained**: Sari continues to use one global DB (`~/.local/share/sari/index.db`).
- **Write contention hardening**: Added SQLite `busy_timeout` and a cross-process write gate lock (`.write.lock`) for safer concurrent indexing.
- **MCP debug log hardening**:
  - Debug traffic logging is now **off by default**.
  - Enable only with `SARI_MCP_DEBUG_LOG=1`.
  - Logs are now summarized/redacted (no full request/response body dump).
- **Workspace root-id stabilization**:
  - Added explicit workspace root-id path (`root_id_for_workspace`) for nested workspace safety.
  - Path resolution now uses explicit workspace scope by default.
- **Legacy compatibility is now opt-in**:
  - Default mode is strict (`SARI_*` namespaced env only).
  - Legacy fallback can be enabled only with `SARI_ALLOW_LEGACY=1`.

---

## 📜 License
Apache License 2.0
