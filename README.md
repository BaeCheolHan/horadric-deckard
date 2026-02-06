# Sari (사리)

[🇰🇷 한국어 가이드 (Korean Guide)](README_KR.md)

**Sari** is a high-performance **Local Code Search Agent** implementing the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It empowers AI assistants (like Claude, Cursor, Codex) to efficiently navigate, understand, and search large codebases without sending code to external servers.

> **Key Features:**
> - ⚡ **Fast Indexing:** SQLite FTS5 + AST-based symbol extraction.
> - 🔍 **Smart Search:** Hybrid ranking (Keyword + Symbol structure).
> - 🧠 **Code Intelligence:** Call graphs, snippets management, and domain context archiving.
> - 🔒 **Local & Secure:** All data remains on your machine. No external API dependency.

---

## 🚀 Installation & Setup

This section is written for first-time setup and daily use.

### Prerequisites
- Python `3.9+`
- One package manager: `uv` (recommended) or `pip`
- A workspace path you want Sari to index

Check Python:
```bash
python3 --version
```

### 5-Minute Quickstart (Recommended Path)
1. Install Sari.
```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y --update
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y --update
```

2. Go to your project root.
```bash
cd /absolute/path/to/your/project
```

3. Start daemon + HTTP for this workspace.
```bash
sari daemon start -d
```

4. Check health.
```bash
sari status
sari doctor
```

5. Connect your MCP client (see **Client Configuration** below).

### Alternative Install Methods
`uv`:
```bash
uv tool install sari
uv tool install "sari[full]"   # optional extras
uv x sari status               # run without install
```

`pip`:
```bash
pip install sari
pip install "sari[full]"       # optional extras
```

### Reinstall From PyPI (Release Validation)
Use this when you want to verify the packaged release (e.g., MCP connection fix) without local source interference.

```bash
# 1) Remove existing tool environment
uv tool uninstall sari

# 2) Force reinstall from PyPI (ignore local project config/sources and cache)
uv tool install --reinstall --refresh --no-cache --no-config --no-sources "sari[full]==0.3.13"

# 3) Verify installed tool version
uv tool list
```

Optional: check all published versions on PyPI before pinning.
```bash
python3 -m pip index versions sari
```

### Pick Your Runtime Mode
- `stdio` mode:
Best default for MCP clients that launch server subprocesses.
- `HTTP` mode:
Useful when stdio transport is unstable in your environment.

Start HTTP directly:
```bash
SARI_WORKSPACE_ROOT=/absolute/path/to/project \
sari --transport http --http-api-port 47777 --http-daemon
```

HTTP MCP endpoint:
```text
http://127.0.0.1:47777/mcp
```

---

## 🏎️ Optional Features (Selectable Extras)

Sari allows you to choose between **low footprint** and **high precision**.

| Extra | Feature | Approx. Size | Installation |
|-------|---------|--------------|--------------|
| **Core** | Standard Regex parsing, FTS5 Search | < 5MB | `pip install sari` |
| **`[cjk]`** | Accurate KR/JP/CN Tokenization | +50MB | `pip install "sari[cjk]"` |
| **`[treesitter]`**| High-precision AST Symbol extraction | +10MB~ | `pip install "sari[treesitter]"` |
| **`[full]`** | All of the above + Tantivy Engine | +100MB+ | `pip install "sari[full]"` |

### Verification
After installation, verify your active features:
```bash
sari doctor
# If 'sari' command is not found, use:
# python3 -m sari doctor
```

---

## 🔌 Client Configuration

Choose one of the options below.

### Option A: Auto-write config (recommended)
Use this when you want Sari to write config for you.
```bash
# Writes workspace-local config files:
#   .codex/config.toml, .gemini/config.toml
sari --cmd install --host codex
sari --cmd install --host gemini
sari --cmd install --host claude
sari --cmd install --host cursor
```

Preview only:
```bash
sari --cmd install --host codex --print
```

### Option B: Manual stdio config
Use this when you want full manual control.

Codex / Gemini TOML (`.codex/config.toml` or `.gemini/config.toml`):
```toml
[mcp_servers.sari]
command = "sari"
args = ["--transport", "stdio", "--format", "pack"]
env = { SARI_WORKSPACE_ROOT = "/absolute/path/to/project" }
startup_timeout_sec = 60
```

Gemini legacy JSON (`~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/absolute/path/to/project"
      }
    }
  }
}
```

Claude Desktop / Cursor JSON:
```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/absolute/path/to/project",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

### Option C: HTTP endpoint mode
Use this if your client prefers MCP-over-HTTP URL.

1. Start HTTP in background:
```bash
SARI_WORKSPACE_ROOT=/absolute/path/to/project \
sari --transport http --http-api-port 47777 --http-daemon
```

2. Point client MCP URL to:
```text
http://127.0.0.1:47777/mcp
```

### Connection Checklist
After configuring the client:
1. Restart the MCP client app/CLI session.
2. Run:
```bash
sari status
```
3. Confirm:
- daemon is running
- HTTP is running
- no connection error in client logs

---

## ⚙️ Configuration Reference

This section lists environment variables that are currently implemented in code.

How to set:
- MCP client: add them under MCP server `env`.
- Shell: prefix command, e.g. `SARI_ENGINE_MODE=sqlite sari status`.

### Core
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_WORKSPACE_ROOT` | Workspace root override. If omitted, Sari auto-detects from CWD. | Auto-detect |
| `SARI_CONFIG` | Config file path override. | `~/.config/sari/config.json` |
| `SARI_FORMAT` | Output format: `pack` or `json`. | `pack` |
| `SARI_RESPONSE_COMPACT` | Compact response payloads for lower token usage. | `1` |
| `SARI_LOG_LEVEL` | Logging level. | `INFO` |

### Daemon / HTTP
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_DAEMON_HOST` | Daemon bind host. | `127.0.0.1` |
| `SARI_DAEMON_PORT` | Daemon TCP port. | `47779` |
| `SARI_HTTP_API_HOST` | HTTP API host (for daemon status routing). | `127.0.0.1` |
| `SARI_HTTP_API_PORT` | HTTP API port. | `47777` |
| `SARI_HTTP_DAEMON` | Background HTTP mode when using `--transport http`. | `0` |
| `SARI_ALLOW_NON_LOOPBACK` | Allow non-loopback bind in HTTP mode. | `0` |

### Search / Index
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_ENGINE_MODE` | `embedded` or `sqlite`. | `embedded` |
| `SARI_ENGINE_AUTO_INSTALL` | Auto-install embedded engine runtime if missing. | `1` |
| `SARI_ENGINE_TOKENIZER` | `auto`, `cjk`, or `latin`. | `auto` |
| `SARI_ENGINE_INDEX_MEM_MB` | Embedded indexing memory budget. | `128` |
| `SARI_ENGINE_MAX_DOC_BYTES` | Max bytes indexed per document. | `4194304` |
| `SARI_ENGINE_PREVIEW_BYTES` | Preview bytes per document. | `8192` |
| `SARI_MAX_DEPTH` | Max scan depth. | `30` |
| `SARI_MAX_PARSE_BYTES` | Max parse file size. | `16777216` |
| `SARI_MAX_AST_BYTES` | Max AST parse file size. | `8388608` |
| `SARI_INDEX_WORKERS` | Index worker count. | `2` |
| `SARI_INDEX_MEM_MB` | Indexing memory cap (`0` means no cap). | `0` |
| `SARI_COALESCE_SHARDS` | Coalescing lock shard count. | `16` |
| `SARI_PARSE_TIMEOUT_SECONDS` | Per-file parse timeout (`0` disables). | `0` |
| `SARI_GIT_CHECKOUT_DEBOUNCE` | Debounce after git-heavy events. | `3.0` |

### Maintenance / Advanced
| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_DRYRUN_LINT` | Enable syntax check in `dry-run-diff`. | `0` |
| `SARI_STORAGE_TTL_DAYS_SNIPPETS` | TTL days for snippets. | `30` |
| `SARI_STORAGE_TTL_DAYS_FAILED_TASKS` | TTL days for failed tasks. | `7` |
| `SARI_STORAGE_TTL_DAYS_CONTEXTS` | TTL days for contexts. | `30` |
| `SARI_CALLGRAPH_PLUGIN` | Custom call-graph plugin module path. | - |
| `SARI_PERSIST_ROOTS` | Persist resolved roots to config. | `0` |

---

## 🛠️ Usage (MCP Tools)

Once connected, your AI assistant can use these tools:

### Core Tools
- **`search`**: Search for code or documentation using keywords or regex.
- **`read_file`**: Read file content (optimized for large files).
- **`list_files`**: List files in the repository.
- **`search_symbols`**: Find classes, functions, or methods by name.
- **`read_symbol`**: Read only the definition of a specific symbol (saves context).

### Intelligence Tools
- **`call_graph`**: Analyze function call relationships (upstream/downstream).
- **`save_snippet` / `get_snippet`**: Save and retrieve important code blocks with tags.
- **`archive_context` / `get_context`**: Store domain knowledge and design decisions.
- **`grep_and_read`**: Search and read top N files in one go (Composite tool).

---

## 🩺 Troubleshooting

### Check Status
You can check the daemon status and indexing progress:

```bash
sari status
```

`sari status` will automatically use the actual HTTP port recorded in
`.codex/tools/sari/data/server.json` (workspace-local). The daemon port is
discovered via the global registry at `~/.local/share/sari/server.json`, so
clients can reconnect without manual port changes.

#### If Daemon Port Is Busy
If you see a message like "Daemon already running" but things still don't work,
another process may be using the default port.

```bash
# Try a different daemon port:
SARI_DAEMON_PORT=47790 sari daemon start -d
```

#### Run Daemon + HTTP Together
`sari status` talks to the HTTP server, so you should run the daemon and HTTP together.
The daemon auto-starts HTTP for the current workspace.

```bash
# Start both (daemon will auto-start HTTP):
sari daemon start -d

# If you need a custom workspace:
SARI_WORKSPACE_ROOT=/path/to/workspace sari daemon start -d
```

#### Zero-Downtime Upgrade (Port Split)
You can run a new daemon+HTTP on different ports, switch clients, then stop the old one.

```bash
# Start new instance on alternate ports:
sari daemon start -d --daemon-port 47790 --http-port 47778

# Check new instance:
sari status --daemon-port 47790 --http-port 47778
```

### Run Doctor
Diagnose issues with your environment or installation:

```bash
sari doctor
```

Advanced doctor flags (including `--auto-fix`) are available via:
```bash
python3 -m sari.mcp.cli doctor --auto-fix
```

### Update
Update Sari using the installer script:

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --update -y
```

After updating, restart the daemon to load the new version:

```bash
pkill -f "sari.mcp.daemon"
sari daemon start -d
```

The bootstrap script now starts a new daemon on a free port automatically
to allow zero-downtime updates.

### Storage Maintenance

To prevent unlimited growth of auxiliary data (snippets, error logs, etc.), Sari implements TTL (Time-To-Live) policies.
Existing data is automatically cleaned up based on TTL settings, or you can manually trigger it.

**Manual Prune:**
```bash
# Prune all tables using default/configured TTL
python3 -m sari.mcp.cli prune

# Prune specific table with custom days
python3 -m sari.mcp.cli prune --table failed_tasks --days 3
```

**TTL Configuration (Environment Variables):**
- `SARI_STORAGE_TTL_DAYS_SNIPPETS` (Default: 30)
- `SARI_STORAGE_TTL_DAYS_FAILED_TASKS` (Default: 7)
- `SARI_STORAGE_TTL_DAYS_CONTEXTS` (Default: 30)

### Uninstall
To remove Sari, indexed data, and default configs:

```bash
# macOS/Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall

# Windows
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - --uninstall
```

To also remove workspace-local caches (if used), pass the workspace root:

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall --workspace-root /path/to/project
```

The uninstall command also scans your home directory for `.codex/tools/sari` caches and removes them (best effort).

If you set `SARI_CONFIG` to a custom path and want that file removed too, pass:

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall --force-config
```

---

## 📜 License

Apache License 2.0
