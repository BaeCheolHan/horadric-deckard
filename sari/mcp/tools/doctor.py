#!/usr/bin/env python3
"""
Doctor tool for Local Search MCP Server.
Returns structured diagnostics (no ANSI/prints).
"""
import json
import os
import socket
import shutil
import sys
import importlib
from pathlib import Path
from typing import Any, Dict, List
from sari.core.cjk import lindera_available, lindera_dict_uri, lindera_error
from sari.core.db import LocalSearchDB
from sari.core.config import Config
from sari.core.workspace import WorkspaceManager
from sari.core.server_registry import ServerRegistry
from sari.mcp.cli import get_daemon_address, is_daemon_running, read_pid, _get_http_host_port, _is_http_running


def _result(name: str, passed: bool, error: str = "") -> dict[str, Any]:
    return {"name": name, "passed": passed, "error": error}


def _check_db(ws_root: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cfg_path = WorkspaceManager.resolve_config_path(ws_root)
    cfg = Config.load(cfg_path, workspace_root_override=ws_root)
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        results.append(_result("DB Existence", False, f"DB not found at {db_path}"))
        return results

    try:
        db = LocalSearchDB(str(db_path))
    except Exception as e:
        results.append(_result("DB Access", False, str(e)))
        return results

    results.append(_result("DB FTS5 Support", bool(db.fts_enabled), "FTS5 module missing in SQLite" if not db.fts_enabled else ""))
    try:
        def _cols(table: str) -> list[str]:
            cursor = db._read.execute(f"PRAGMA table_info({table})")
            return [r["name"] for r in cursor.fetchall()]
        symbols_cols = _cols("symbols")
        if "end_line" in symbols_cols:
            results.append(_result("DB Schema", True))
        else:
            results.append(_result("DB Schema", False, "Column 'end_line' missing in 'symbols'. Run update."))
        if "qualname" in symbols_cols and "symbol_id" in symbols_cols:
            results.append(_result("DB Schema Symbol IDs", True))
        else:
            results.append(_result("DB Schema Symbol IDs", False, "Missing qualname/symbol_id in 'symbols'."))
        rel_cols = _cols("symbol_relations")
        if "from_symbol_id" in rel_cols and "to_symbol_id" in rel_cols:
            results.append(_result("DB Schema Relations IDs", True))
        else:
            results.append(_result("DB Schema Relations IDs", False, "Missing from_symbol_id/to_symbol_id in 'symbol_relations'."))
        snippet_cols = _cols("snippets")
        if "anchor_before" in snippet_cols and "anchor_after" in snippet_cols:
            results.append(_result("DB Schema Snippet Anchors", True))
        else:
            results.append(_result("DB Schema Snippet Anchors", False, "Missing anchor_before/anchor_after in 'snippets'."))
        ctx_cols = _cols("contexts")
        if all(c in ctx_cols for c in ("source", "valid_from", "valid_until", "deprecated")):
            results.append(_result("DB Schema Context Validity", True))
        else:
            results.append(_result("DB Schema Context Validity", False, "Missing validity columns in 'contexts'."))
        row = db._read.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='snippet_versions'"
        ).fetchone()
        results.append(_result("DB Schema Snippet Versions", bool(row), "snippet_versions table missing" if not row else ""))
        row = db._read.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failed_tasks'"
        ).fetchone()
        results.append(_result("DB Schema Failed Tasks", bool(row), "failed_tasks table missing" if not row else ""))
        if row:
            total_failed, high_failed = db.count_failed_tasks()
            if high_failed >= 3:
                results.append(_result("Failed Tasks (DLQ)", False, f"{high_failed} tasks exceeded retry threshold"))
            else:
                results.append(_result("Failed Tasks (DLQ)", True, f"pending={total_failed}"))
    except Exception as e:
        results.append(_result("DB Schema Check", False, str(e)))
    finally:
        try:
            db.close()
        except Exception:
            pass

    return results


def _platform_tokenizer_tag() -> str:
    import platform
    plat = sys.platform
    arch = platform.machine().lower()
    if plat.startswith("darwin"):
        if arch in {"arm64", "aarch64"}:
            return "macosx_11_0_arm64"
        if arch in {"x86_64", "amd64"}:
            return "macosx_10_9_x86_64"
        return "macosx"
    if plat.startswith("win"):
        return "win_amd64"
    if plat.startswith("linux"):
        if arch in {"aarch64", "arm64"}:
            return "manylinux_2_17_aarch64"
        return "manylinux_2_17_x86_64"
    return "unknown"


def _check_engine_tokenizer_data() -> dict[str, Any]:
    """Check if tokenizer data (lindera) is installed as a package."""
    try:
        import lindera_dictionary_ipadic
        return _result("CJK Tokenizer Data", True, f"installed ({getattr(lindera_dictionary_ipadic, '__version__', 'unknown')})")
    except ImportError:
        return _result("CJK Tokenizer Data", False, "package 'lindera-dictionary-ipadic' not installed (optional)")
    except Exception as e:
        return _result("CJK Tokenizer Data", False, str(e))

def _check_tree_sitter() -> dict[str, Any]:
    """Check if Tree-sitter and language parsers are installed."""
    try:
        from sari.core.parsers.ast_engine import ASTEngine
        engine = ASTEngine()
        if not engine.enabled:
             return _result("Tree-sitter Support", False, "core 'tree-sitter' package not installed (optional)")
        
        # Check specific languages
        langs = ["python", "javascript", "typescript", "java", "go", "rust", "cpp"]
        installed = []
        for lang in langs:
             if engine._get_language(lang):
                 installed.append(lang)
        
        if installed:
            return _result("Tree-sitter Support", True, f"enabled for: {', '.join(installed)}")
        return _result("Tree-sitter Support", True, "core enabled but no language parsers loaded yet")
    except Exception as e:
        return _result("Tree-sitter Support", False, str(e))

def _check_lindera_dictionary() -> dict[str, Any]:
    if lindera_available():
        uri = lindera_dict_uri() or "embedded://ipadic"
        return _result("Lindera Engine", True, f"active dict={uri}")
    err = lindera_error() or "not available"
    # If package is missing, it's not an error but an optional state
    is_error = "not installed" not in err
    return _result("Lindera Engine", not is_error, err)


def _check_port(port: int, label: str) -> dict[str, Any]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return _result(f"{label} Port {port} Availability", True)
    except OSError as e:
        return _result(f"{label} Port {port} Availability", False, f"Address in use or missing permission: {e}")
    finally:
        try:
            s.close()
        except Exception:
            pass


def _check_network() -> dict[str, Any]:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return _result("Network Check", True)
    except OSError as e:
        return _result("Network Check", False, f"Unreachable: {e}")


def _check_disk_space(ws_root: str, min_gb: float) -> dict[str, Any]:
    try:
        total, used, free = shutil.disk_usage(ws_root)
        free_gb = free / (1024**3)
        if free_gb < min_gb:
            return _result("Disk Space", False, f"Low space: {free_gb:.2f} GB (Min: {min_gb} GB)")
        return _result("Disk Space", True)
    except Exception as e:
        return _result("Disk Space", False, str(e))


def _check_daemon() -> dict[str, Any]:
    host, port = get_daemon_address()
    running = is_daemon_running(host, port)
    if running:
        pid = read_pid()
        return _result("Sari Daemon", True, f"Running on {host}:{port} (PID: {pid})")
    return _result("Sari Daemon", False, "Not running")


def _check_http_service(host: str, port: int) -> dict[str, Any]:
    running = _is_http_running(host, port)
    if running:
        return _result("HTTP API", True, f"Running on {host}:{port}")
    return _result("HTTP API", False, f"Not running on {host}:{port}")


def _check_search_first_usage(usage: Dict[str, Any], mode: str) -> dict[str, Any]:
    violations = int(usage.get("read_without_search", 0))
    searches = int(usage.get("search", 0))
    symbol_searches = int(usage.get("search_symbols", 0))
    if violations == 0:
        return _result("Search-First Usage", True, "")
    policy = mode if mode in {"off", "warn", "enforce"} else "unknown"
    error = (
        f"Search-first policy {policy}: {violations} read call(s) without prior search "
        f"(search={searches}, search_symbols={symbol_searches})."
    )
    return _result("Search-First Usage", False, error)

def _check_callgraph_plugin() -> dict[str, Any]:
    mod_path = os.environ.get("SARI_CALLGRAPH_PLUGIN", "").strip()
    if not mod_path:
        return _result("CallGraph Plugin", True, "not configured")
    mods = [m.strip() for m in mod_path.split(",") if m.strip()]
    failed = []
    meta = []
    for m in mods:
        try:
            mod = importlib.import_module(m)
            version = getattr(mod, "__version__", "")
            api = getattr(mod, "__callgraph_plugin_api__", None)
            if api is not None:
                meta.append(f"{m}@{version} api={api}")
            else:
                meta.append(f"{m}{'@' + str(version) if version else ''}")
        except Exception:
            failed.append(m)
    if failed:
        return _result("CallGraph Plugin", False, f"failed to load: {', '.join(failed)}")
    detail = "loaded"
    if meta:
        detail = "loaded: " + ", ".join(meta)
    return _result("CallGraph Plugin", True, detail)

def _recommendations(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    recs: list[dict[str, str]] = []
    for r in results:
        if r.get("passed"):
            continue
        name = str(r.get("name") or "")
        if name == "DB Existence":
            recs.append({"name": name, "action": "Run `sari init` to create config, then start daemon or run a full scan."})
        elif name == "DB Access":
            recs.append({"name": name, "action": "Check file permissions and ensure no other process locks the DB."})
        elif name in {
            "DB Schema Symbol IDs",
            "DB Schema Relations IDs",
            "DB Schema Snippet Anchors",
            "DB Schema Context Validity",
            "DB Schema Snippet Versions",
        }:
            recs.append({"name": name, "action": "Upgrade to latest code, then run a full rescan (or remove old DB to rebuild)."})
        elif name == "Engine Tokenizer Data":
            recs.append({"name": name, "action": "Install CJK support: pip install 'sari[cjk]'"})
        elif name == "Lindera Dictionary":
            recs.append({"name": name, "action": "Install CJK support: pip install 'sari[cjk]'"})
        elif name == "CJK Tokenizer Data" or name == "Lindera Engine":
            recs.append({"name": name, "action": "Install CJK support: pip install 'sari[cjk]'"})
        elif name == "Tree-sitter Support":
             recs.append({"name": name, "action": "Install high-precision parsers: pip install 'sari[treesitter]'"})
        elif name.startswith("Daemon Port") or name.startswith("HTTP Port"):
            recs.append({"name": name, "action": "Change port or stop the conflicting process."})
        elif name == "Sari Daemon":
            recs.append({"name": name, "action": "Start daemon with `sari daemon start`."})
        elif name == "Network Check":
            recs.append({"name": name, "action": "If offline, rerun doctor with include_network=false or check firewall."})
        elif name == "Disk Space":
            recs.append({"name": name, "action": "Free disk space or move workspace to a larger volume."})
        elif name == "Search-First Usage":
            recs.append({"name": name, "action": "Enable search-first or update client to respect search-before-read."})
    return recs

def _auto_fixable(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for r in results:
        if r.get("passed"):
            continue
        name = str(r.get("name") or "")
        if name == "DB Schema Symbol IDs":
            actions.append({"name": name, "action": "db_migrate"})
        elif name == "DB Schema Relations IDs":
            actions.append({"name": name, "action": "db_migrate"})
        elif name == "DB Schema Snippet Anchors":
            actions.append({"name": name, "action": "db_migrate"})
        elif name == "DB Schema Context Validity":
            actions.append({"name": name, "action": "db_migrate"})
        elif name == "DB Schema Snippet Versions":
            actions.append({"name": name, "action": "db_migrate"})
    return actions

def _run_auto_fixes(ws_root: str, actions: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not actions:
        return []
    results: list[dict[str, Any]] = []
    try:
        cfg_path = WorkspaceManager.resolve_config_path(ws_root)
        cfg = Config.load(cfg_path, workspace_root_override=ws_root)
        db = LocalSearchDB(cfg.db_path)
        db.close()
        results.append(_result("Auto Fix DB Migrate", True, "Schema migration applied"))
    except Exception as e:
        results.append(_result("Auto Fix DB Migrate", False, str(e)))
    return results

def _run_rescan(ws_root: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    results.append(_result("Auto Fix Rescan Start", True, "scan_once starting"))
    try:
        cfg_path = WorkspaceManager.resolve_config_path(ws_root)
        cfg = Config.load(cfg_path, workspace_root_override=ws_root)
        db = LocalSearchDB(cfg.db_path)
        from sari.core.indexer import Indexer
        indexer = Indexer(cfg, db, indexer_mode="leader", indexing_enabled=True, startup_index_enabled=True)
        indexer.scan_once()
        db.close()
        results.append(_result("Auto Fix Rescan", True, "scan_once completed"))
    except Exception as e:
        results.append(_result("Auto Fix Rescan", False, str(e)))
    return results


def execute_doctor(args: Dict[str, Any]) -> Dict[str, Any]:
    ws_root = WorkspaceManager.resolve_workspace_root()

    include_network = bool(args.get("include_network", True))
    include_port = bool(args.get("include_port", True))
    include_db = bool(args.get("include_db", True))
    include_disk = bool(args.get("include_disk", True))
    include_daemon = bool(args.get("include_daemon", True))
    include_venv = bool(args.get("include_venv", True))
    include_marker = bool(args.get("include_marker", False))
    port = int(args.get("port", 0))
    min_disk_gb = float(args.get("min_disk_gb", 1.0))

    results: list[dict[str, Any]] = []

    if include_venv:
        in_venv = sys.prefix != sys.base_prefix
        results.append(_result("Virtualenv", True, "" if in_venv else "Not running in venv (ok)"))

    if include_marker:
        results.append(_result("Workspace Marker (.codex-root)", True, "Marker check deprecated"))

    if include_daemon:
        results.append(_check_daemon())

    if include_port:
        daemon_host, daemon_port = get_daemon_address()
        daemon_running = is_daemon_running(daemon_host, daemon_port)
        if daemon_running:
            results.append(_result("Daemon Port", True, f"In use by running daemon {daemon_host}:{daemon_port}"))
        else:
            results.append(_check_port(daemon_port, "Daemon"))

        http_host, http_port = _get_http_host_port(port_override=port if port else None)
        results.append(_check_http_service(http_host, http_port))
        if not _is_http_running(http_host, http_port):
            results.append(_check_port(http_port, "HTTP"))

    if include_network:
        results.append(_check_network())

    if include_db:
        results.extend(_check_db(ws_root))
        results.append(_check_engine_tokenizer_data())
        results.append(_check_lindera_dictionary())
        results.append(_check_tree_sitter())

    if include_disk:
        results.append(_check_disk_space(ws_root, min_disk_gb))

    usage = args.get("search_usage")
    if isinstance(usage, dict):
        mode = str(args.get("search_first_mode", "unknown"))
        results.append(_check_search_first_usage(usage, mode))

    results.append(_check_callgraph_plugin())

    auto_fix = bool(args.get("auto_fix", False))
    auto_fix_rescan = bool(args.get("auto_fix_rescan", False))
    auto_fix_results: list[dict[str, Any]] = []
    if auto_fix:
        actions = _auto_fixable(results)
        auto_fix_results = _run_auto_fixes(ws_root, actions)
        results.extend(auto_fix_results)
        if auto_fix_rescan:
            if any(not r.get("passed") for r in auto_fix_results):
                res = [_result("Auto Fix Rescan Skipped", False, "auto-fix failed; rescan skipped")]
                auto_fix_results.extend(res)
                results.extend(res)
            else:
                res = _run_rescan(ws_root)
                auto_fix_results.extend(res)
                results.extend(res)

    output = {
        "workspace_root": ws_root,
        "results": results,
        "recommendations": _recommendations(results),
        "auto_fix": auto_fix_results,
    }

    compact = str(os.environ.get("SARI_RESPONSE_COMPACT") or "1").strip().lower() not in {"0", "false", "no", "off"}
    payload = json.dumps(output, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(output, ensure_ascii=False, indent=2)
    try:
        from sari.mcp.tools._util import mcp_response, pack_header, pack_line, pack_encode_text
    except Exception:
        from _util import mcp_response, pack_header, pack_line, pack_encode_text

    def build_pack() -> str:
        lines = [pack_header("doctor", {}, returned=1)]
        lines.append(pack_line("t", single_value=pack_encode_text(payload)))
        return "\n".join(lines)

    return mcp_response(
        "doctor",
        build_pack,
        lambda: {"content": [{"type": "text", "text": payload}]},
    )
