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

Sari uses a **two-step flow**:
1) Install Sari explicitly.
2) Add MCP configuration that only *runs* the server (no downloads on launch).

### Step 1: Install

#### macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y --update
```

#### Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y --update
```

---

### Step 2: MCP Configuration (No Auto-Download)

#### 🍎 macOS / Linux

**Cursor / Claude Desktop Config:**
```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/path/to/your/project",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

#### 🪟 Windows (PowerShell)

**Cursor / Claude Desktop Config:**
```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "C:\\path\\to\\your\\project",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

---

### Gemini CLI

Gemini CLI reads MCP servers from `settings.json`. Add a Sari entry to your Gemini settings and restart the CLI.

**Settings file locations:**
- **macOS/Linux:** `~/.gemini/settings.json`
- **Windows:** `%USERPROFILE%\.gemini\settings.json`

```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/path/to/your/project",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

### Codex CLI (HTTP)

Codex CLI currently expects MCP-over-HTTP. Run Sari in HTTP mode and configure the MCP server with a URL.

```bash
# Start HTTP MCP server
sari --transport http --http-api-port 47777
```

```toml
[mcp_servers.sari]
url = "http://127.0.0.1:47777/mcp"
enabled = true
```


### Option 2: Manual Installation (Pip)

If you prefer to manage the package manually:

```bash
# Install from PyPI
pip install sari

# Run MCP Server
sari --transport stdio --format pack
```

---

## ⚙️ Configuration Reference

Variables are categorized into **Installation-time** and **Runtime** settings.

### How to set environment variables

- **MCP Client**: Add to the `env` block of your MCP server configuration.
- **CLI**: Prefix the command, e.g., `SARI_ENGINE_MODE=sqlite sari status`.

```json
"env": {
  "SARI_WORKSPACE_ROOT": "/path/to/project",
  "SARI_ENGINE_TOKENIZER": "cjk"
}
```

### A. Installation & Bootstrapping
Settings affecting the installation scripts (`install.py`, `bootstrap.sh`).

| Variable | Description | Default |
|----------|-------------|---------|
| `XDG_DATA_HOME` | Custom data directory for installation. Sari installs to `$XDG_DATA_HOME/sari`. | `~/.local/share` |
| `SARI_SKIP_INSTALL` | Set `1` to skip automatic pip install/upgrade on startup **when using the bootstrap script**. Useful for development or offline usage. | `0` |
| `SARI_NO_INTERACTIVE`| Set `1` to disable interactive prompts during installation (assumes 'yes'). | `0` |

### B. System & Runtime
Settings controlling the MCP server loop and behaviors. Add these to your `env` config.

#### 1. Core & System
Essential settings for basic operation. (`SARI_` prefix is also supported for backward compatibility).

| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_WORKSPACE_ROOT` | **(Required)** Absolute path to the project root. Auto-detected if omitted. | Auto-detect |
| `SARI_ROOTS_JSON` | JSON array of strings for multiple workspace roots. e.g., `["/path/a", "/path/b"]` | - |
| `SARI_DB_PATH` | Custom path for the SQLite database file. | `~/.local/share/sari/data/<hash>/index.db` |
| `SARI_CONFIG` | Path to a specific config file to load. | `~/.config/sari/config.json` |
| `SARI_RESPONSE_COMPACT` | Minify JSON responses (`pack` format) to save LLM tokens. Set `0` for pretty-print debugging. | `1` (Enabled) |
| `SARI_FORMAT` | Output format for CLI tools. `pack` (text-based) or `json`. | `pack` |

#### 2. Search Engine
Settings to tune search quality and backend behavior.

| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_ENGINE_MODE` | Search backend. `embedded` uses Tantivy (faster, smart ranking), `sqlite` uses FTS5 (slower, fallback). | `embedded` |
| `SARI_ENGINE_TOKENIZER` | Tokenizer strategy. `auto` (detects), `cjk` (optimized for KR/CN/JP), `latin` (standard). | `auto` |
| `SARI_ENGINE_AUTO_INSTALL` | Automatically install engine binaries (Tantivy) if missing. | `1` (Enabled) |
| `SARI_ENGINE_SUGGEST_FILES`| File count threshold to suggest upgrading to Tantivy engine in status checks. | `10000` |
| `SARI_LINDERA_DICT_PATH` | Path to custom Lindera dictionary for CJK tokenization (Advanced). | - |

#### 3. Indexing & Performance
Fine-tune resource usage and concurrency.

| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_COALESCE_SHARDS` | Number of lock shards for indexing concurrency. Increase for massive repos with frequent changes. | `16` |
| `SARI_PARSE_TIMEOUT_SECONDS`| Timeout per file parsing in seconds. Set `0` to disable timeout. Prevents parser hangs. | `0` |
| `SARI_PARSE_TIMEOUT_WORKERS`| Worker threads for parsing with timeout. | `2` |
| `SARI_MAX_PARSE_BYTES` | Max file size to attempt parsing (bytes). Larger files are skipped or sampled. | `16MB` |
| `SARI_MAX_AST_BYTES` | Max file size to attempt AST extraction (bytes). | `8MB` |
| `SARI_GIT_CHECKOUT_DEBOUNCE`| Seconds to wait after git checkout before starting bulk indexing. | `3.0` |
| `SARI_FOLLOW_SYMLINKS` | Follow symbolic links during file scanning. **Caution:** May cause infinite loops if circular links exist. | `0` (Disabled) |
| `SARI_READ_MAX_BYTES` | Max bytes returned by `read_file` tool. Prevents context overflow. | `1MB` |

#### 4. Network & Security
Connectivity settings for the daemon.

| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_DAEMON_HOST` | Host address for the background daemon. | `127.0.0.1` |
| `SARI_DAEMON_PORT` | TCP port for the daemon. | `47779` |
| `SARI_HTTP_API_PORT` | Port for the HTTP API server (optional). | `47777` |
| `SARI_ALLOW_NON_LOOPBACK` | Allow connections from non-localhost IPs. **Security Risk:** Only enable in trusted networks. | `0` (Disabled) |

#### 5. Advanced / Debug
Developer options for debugging and plugin extension.

| Variable | Description | Default |
|----------|-------------|---------|
| `SARI_LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |
| `SARI_DRYRUN_LINT` | Enable syntax checking (linting) in `dry-run-diff`. | `0` (Disabled) |
| `SARI_PERSIST_ROOTS` | Set `1` to persist detected roots to `config.json`. | `0` (Disabled) |
| `SARI_CALLGRAPH_PLUGIN` | Python module path for custom static analysis plugin. | - |
| `SARI_DLQ_POLL_SECONDS` | Interval to retry failed indexing tasks (Dead Letter Queue). | `60` |

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
sari doctor --auto-fix
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

If you set `SARI_CONFIG` or `SARI_CONFIG` to a custom path and want that file removed too, pass:

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall --force-config
```

---

## 📜 License

Apache License 2.0

```
