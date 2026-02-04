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

Sari supports **automatic installation** via MCP configuration (Recommended) or manual installation via `pip`.

### Option 1: Automatic Installation (Recommended)

Add the following configuration to your MCP client (Cursor, Claude Desktop, etc.). Sari will be automatically installed (via `pip`) and updated upon launch.

#### 🍎 macOS / Linux

**Cursor / Claude Desktop Config:**
```json
{
  "mcpServers": {
    "sari": {
      "command": "bash",
      "args": [
        "-lc",
        "export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin && (curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y || true) && exec ~/.local/share/sari/bootstrap.sh --transport stdio"
      ],
      "env": {
        "DECKARD_WORKSPACE_ROOT": "/path/to/your/project",
        "DECKARD_RESPONSE_COMPACT": "1"
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
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y; & $env:LOCALAPPDATA\sari\bootstrap.bat --transport stdio"
      ],
      "env": {
        "DECKARD_WORKSPACE_ROOT": "C:\\path\\to\\your\\project",
        "DECKARD_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

---


### Option 2: Manual Installation (Pip)

If you prefer to manage the package manually:

```bash
# Install from PyPI
pip install sari

# Run MCP Server
python3 -m sari --transport stdio
```

---

## ⚙️ Configuration Reference

### How to Configure
You can customize Sari's behavior by setting environment variables.
- **MCP Config**: Add them to the `env` dictionary in your `config.json` or `config.toml`.
- **CLI**: Prefix the command, e.g., `DECKARD_ENGINE_MODE=sqlite sari status`.

```json
"env": {
  "DECKARD_WORKSPACE_ROOT": "/path/to/project",
  "DECKARD_ENGINE_TOKENIZER": "cjk"
}
```

### 1. Core & System
Essential settings for basic operation.

| Variable | Description | Default |
|----------|-------------|---------|
| `DECKARD_WORKSPACE_ROOT` | **(Required)** Absolute path to the project root. Auto-detected if omitted, but recommended to set explicitly. | Auto-detect |
| `DECKARD_DB_PATH` | Custom path for the SQLite database file. | `~/.local/share/sari/data/<hash>/index.db` |
| `DECKARD_CONFIG` | Path to a specific config file to load. | `~/.config/sari/config.json` |
| `DECKARD_RESPONSE_COMPACT` | Minify JSON responses (`pack` format) to save LLM tokens. Set `0` for pretty-print debugging. | `1` (Enabled) |
| `DECKARD_FORMAT` | Output format for CLI tools. `pack` (text-based) or `json`. | `pack` |

### 2. Search Engine
Settings to tune search quality and backend behavior.

| Variable | Description | Default |
|----------|-------------|---------|
| `DECKARD_ENGINE_MODE` | Search backend. `embedded` uses Tantivy (faster, smart ranking), `sqlite` uses FTS5 (slower, fallback). | `embedded` |
| `DECKARD_ENGINE_TOKENIZER` | Tokenizer strategy. `auto` (detects), `cjk` (optimized for KR/CN/JP), `latin` (standard). | `auto` |
| `DECKARD_ENGINE_AUTO_INSTALL` | Automatically install engine binaries (Tantivy) if missing. | `1` (Enabled) |
| `DECKARD_ENGINE_SUGGEST_FILES`| File count threshold to suggest upgrading to Tantivy engine in status checks. | `10000` |
| `DECKARD_LINDERA_DICT_PATH` | Path to custom Lindera dictionary for CJK tokenization (Advanced). | - |

### 3. Indexing & Performance
Fine-tune resource usage and concurrency.

| Variable | Description | Default |
|----------|-------------|---------|
| `DECKARD_COALESCE_SHARDS` | Number of lock shards for indexing concurrency. Increase for massive repos with frequent changes. | `16` |
| `DECKARD_PARSE_TIMEOUT_SECONDS`| Timeout per file parsing in seconds. Set `0` to disable timeout. Prevents parser hangs. | `0` |
| `DECKARD_PARSE_TIMEOUT_WORKERS`| Worker threads for parsing with timeout. | `2` |
| `DECKARD_MAX_PARSE_BYTES` | Max file size to attempt parsing (bytes). Larger files are skipped or sampled. | `16MB` |
| `DECKARD_MAX_AST_BYTES` | Max file size to attempt AST extraction (bytes). | `8MB` |
| `DECKARD_GIT_CHECKOUT_DEBOUNCE`| Seconds to wait after git checkout before starting bulk indexing. | `3.0` |
| `DECKARD_FOLLOW_SYMLINKS` | Follow symbolic links during file scanning. **Caution:** May cause infinite loops if circular links exist. | `0` (Disabled) |
| `DECKARD_READ_MAX_BYTES` | Max bytes returned by `read_file` tool. Prevents context overflow. | `1MB` |

### 4. Network & Security
Connectivity settings for the daemon.

| Variable | Description | Default |
|----------|-------------|---------|
| `DECKARD_DAEMON_HOST` | Host address for the background daemon. | `127.0.0.1` |
| `DECKARD_DAEMON_PORT` | TCP port for the daemon. | `47779` |
| `DECKARD_HTTP_API_PORT` | Port for the HTTP API server (optional). | `47777` |
| `DECKARD_ALLOW_NON_LOOPBACK` | Allow connections from non-localhost IPs. **Security Risk:** Only enable in trusted networks. | `0` (Disabled) |

### 5. Advanced / Debug
Developer options for debugging and plugin extension.

| Variable | Description | Default |
|----------|-------------|---------|
| `DECKARD_CALLGRAPH_PLUGIN` | Python module path for custom static analysis plugin. | - |
| `DECKARD_DRYRUN_LINT` | Enable linter checks (ruff/eslint) in `dry_run_diff` tool. | `0` |
| `DECKARD_DLQ_POLL_SECONDS` | Interval to retry failed indexing tasks (Dead Letter Queue). | `60` |
| `DECKARD_LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |

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
# If installed automatically:
~/.local/share/sari/bootstrap.sh status

# If installed via pip:
sari status
```

### Run Doctor
Diagnose issues with your environment or installation:

```bash
# If installed automatically:
~/.local/share/sari/bootstrap.sh doctor --auto-fix

# If installed via pip:
sari doctor --auto-fix
```

### Uninstall
To remove Sari and all indexed data:

```bash
# macOS/Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall

# Windows
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - --uninstall
```

---

## 📜 License

Apache License 2.0

```