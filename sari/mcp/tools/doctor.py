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
import inspect
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sari.core.cjk import lindera_available, lindera_dict_uri, lindera_error
from sari.core.db import LocalSearchDB
from sari.core.config import Config
from sari.core.settings import settings
from sari.core.workspace import WorkspaceManager
from sari.core.server_registry import ServerRegistry, get_registry_path
from sari.mcp.cli import get_daemon_address, is_daemon_running, read_pid, _get_http_host_port, _is_http_running, _identify_sari_daemon as _cli_identify

def _identify_sari_daemon(host: str, port: int):
    return _cli_identify(host, port)


def _result(name: str, passed: bool, error: str = "", warn: bool = False) -> dict[str, Any]:
    return {"name": name, "passed": passed, "error": error, "warn": warn}


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
    if lindera_available():
        uri = lindera_dict_uri() or "embedded://ipadic"
        return _result("CJK Tokenizer", True, f"active ({uri})")
    err = lindera_error() or "not available"
    return _result("CJK Tokenizer", False, f"{err} (package 'lindera-python-ipadic' optional)")

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


def _check_embedded_engine_module() -> dict[str, Any]:
    """Check if embedded engine dependency (tantivy) is importable."""
    try:
        import tantivy  # type: ignore
        ver = getattr(tantivy, "__version__", "unknown")
        return _result("Embedded Engine Module", True, str(ver))
    except Exception as e:
        return _result("Embedded Engine Module", False, f"{type(e).__name__}: {e}")

def _check_windows_write_lock_support() -> dict[str, Any]:
    if os.name != "nt":
        return _result("Windows Write Lock", True, "non-windows platform")
    try:
        import msvcrt  # type: ignore
        ok = hasattr(msvcrt, "locking") and hasattr(msvcrt, "LK_LOCK")
        if ok:
            return _result("Windows Write Lock", True, "msvcrt.locking available")
        return _result("Windows Write Lock", False, "msvcrt.locking is unavailable")
    except Exception as e:
        return _result("Windows Write Lock", False, f"{type(e).__name__}: {e}")

def _check_db_migration_safety() -> dict[str, Any]:
    try:
        src = inspect.getsource(LocalSearchDB._check_and_migrate)
    except Exception as e:
        return _result("DB Migration Safety", False, f"source read failed: {e}")
    destructive_tokens = ("os.remove(", "unlink(")
    if any(tok in src for tok in destructive_tokens):
        return _result("DB Migration Safety", False, "destructive delete path detected in migration precheck")
    return _result("DB Migration Safety", True, "non-destructive precheck policy")

def _check_engine_sync_dlq(ws_root: str) -> dict[str, Any]:
    try:
        cfg_path = WorkspaceManager.resolve_config_path(ws_root)
        cfg = Config.load(cfg_path, workspace_root_override=ws_root)
        db = LocalSearchDB(cfg.db_path)
        try:
            row = db._read.execute(
                "SELECT COUNT(*), COALESCE(MAX(attempts),0) FROM failed_tasks WHERE error LIKE 'engine_sync_error:%'"
            ).fetchone()
            count = int(row[0]) if row else 0
            max_attempts = int(row[1]) if row else 0
            if count == 0:
                return _result("Engine Sync DLQ", True, "no pending engine_sync_error tasks")
            return _result("Engine Sync DLQ", False, f"pending={count} max_attempts={max_attempts}")
        finally:
            try:
                db.close()
            except Exception:
                pass
    except Exception as e:
        return _result("Engine Sync DLQ", False, str(e))

def _check_writer_health(db: Any = None) -> dict[str, Any]:
    try:
        from sari.core.db.storage import GlobalStorageManager
        sm = getattr(GlobalStorageManager, "_instance", None)
        if sm is None:
            return _result("Writer Health", True, "no active storage manager")
        writer = getattr(sm, "writer", None)
        if writer is None:
            return _result("Writer Health", False, "storage manager has no writer")
        thread_obj = getattr(writer, "_thread", None)
        alive = bool(thread_obj and thread_obj.is_alive())
        qsize = int(writer.qsize()) if hasattr(writer, "qsize") else -1
        last_commit = int(getattr(writer, "last_commit_ts", 0) or 0)
        age = int(time.time()) - last_commit if last_commit > 0 else -1
        if not alive:
            return _result("Writer Health", False, f"writer thread not alive (queue={qsize})")
        if qsize > 1000:
            return _result("Writer Health", True, f"writer alive but queue high={qsize}", warn=True)
        if qsize > 0 and age > 120:
            return _result("Writer Health", True, f"writer alive with stale commits age_sec={age}", warn=True)
        detail = f"alive=true queue={qsize}"
        if age >= 0:
            detail += f" last_commit_age_sec={age}"
        return _result("Writer Health", True, detail)
    except Exception as e:
        return _result("Writer Health", False, str(e))

def _check_storage_switch_guard() -> dict[str, Any]:
    try:
        from sari.core.db.storage import GlobalStorageManager
        reason = str(getattr(GlobalStorageManager, "_last_switch_block_reason", "") or "")
        ts = float(getattr(GlobalStorageManager, "_last_switch_block_ts", 0.0) or 0.0)
        if not reason:
            return _result("Storage Switch Guard", True, "no blocked switch")
        age = int(time.time() - ts) if ts > 0 else -1
        msg = f"switch blocked: {reason}"
        if age >= 0:
            msg += f" age_sec={age}"
        return _result("Storage Switch Guard", False, msg)
    except Exception as e:
        return _result("Storage Switch Guard", False, str(e))

def _check_fts_rebuild_policy() -> dict[str, Any]:
    if settings.FTS_REBUILD_ON_START:
        return _result("FTS Rebuild Policy", True, "FTS_REBUILD_ON_START=true may increase startup latency", warn=True)
    return _result("FTS Rebuild Policy", True, "FTS_REBUILD_ON_START=false")


def _check_engine_runtime(ws_root: str) -> dict[str, Any]:
    """Check current runtime engine readiness from config + engine registry."""
    try:
        cfg_path = WorkspaceManager.resolve_config_path(ws_root)
        cfg = Config.load(cfg_path, workspace_root_override=ws_root)
        db = LocalSearchDB(cfg.db_path)
        try:
            from sari.core.settings import settings as _settings
            db.set_settings(_settings)
        except Exception:
            pass
        try:
            from sari.core.engine_registry import get_default_engine
            engine = get_default_engine(db, cfg, cfg.workspace_roots)
            db.set_engine(engine)
            if hasattr(engine, "status"):
                st = engine.status()
                mode = getattr(st, "engine_mode", "unknown")
                ready = bool(getattr(st, "engine_ready", False))
                reason = str(getattr(st, "reason", "") or "")
                hint = str(getattr(st, "hint", "") or "")
                detail = f"mode={mode} ready={str(ready).lower()}"
                if reason:
                    detail += f" reason={reason}"
                if hint:
                    detail += f" hint={hint}"
                passed = ready if mode == "embedded" else True
                return _result("Search Engine Runtime", passed, detail)
            return _result("Search Engine Runtime", False, "engine has no status()")
        finally:
            try:
                if hasattr(db, "engine") and hasattr(db.engine, "close"):
                    db.engine.close()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
    except Exception as e:
        return _result("Search Engine Runtime", False, str(e))


def _check_lindera_dictionary() -> dict[str, Any]:
    # Merged into CJK Tokenizer check above
    return _check_engine_tokenizer_data()


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


def _check_db_integrity(ws_root: str) -> dict[str, Any]:
    """Perform a deep integrity check on the SQLite DB file."""
    try:
        cfg_path = WorkspaceManager.resolve_config_path(ws_root)
        cfg = Config.load(cfg_path, workspace_root_override=ws_root)
        db_path = Path(cfg.db_path)
        
        if not db_path.exists():
            return _result("DB Integrity", False, "DB file missing")
        if db_path.stat().st_size == 0:
            return _result("DB Integrity", False, "DB file is 0 bytes (empty)")
            
        import sqlite3
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cursor = conn.execute("PRAGMA integrity_check(10)")
            res = cursor.fetchone()[0]
            if res == "ok":
                return _result("DB Integrity", True, "SQLite format ok")
            return _result("DB Integrity", False, f"Corruption detected: {res}")
    except Exception as e:
        return _result("DB Integrity", False, f"Check failed: {e}")

def _check_log_errors() -> dict[str, Any]:
    """Scan latest logs for ERROR/CRITICAL patterns without OOM risk."""
    try:
        env_log_dir = os.environ.get("SARI_LOG_DIR")
        log_dir = Path(env_log_dir).expanduser().resolve() if env_log_dir else WorkspaceManager.get_global_log_dir()
        log_file = log_dir / "daemon.log"
        if not log_file.exists():
            return _result("Log Health", True, "No log file yet")
            
        errors = []
        # Safety: Read only the last 1MB of log to avoid OOM
        file_size = log_file.stat().st_size
        read_size = min(file_size, 1024 * 1024) # 1MB
        
        with open(log_file, "rb") as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
            chunk = f.read().decode("utf-8", errors="ignore")
            lines = chunk.splitlines()
            # Only look at errors in the last 500 lines of the 1MB chunk
            for line in lines[-500:]:
                line_upper = line.upper()
                if "ERROR" in line_upper or "CRITICAL" in line_upper:
                    errors.append(line.strip())
                    
        if not errors:
            return _result("Log Health", True, "No recent errors")
        
        # Extract unique symptoms
        unique_errs = []
        for e in errors:
            msg = e.split(" - ")[-1] if " - " in e else e
            if msg not in unique_errs:
                unique_errs.append(msg)
        
        return _result("Log Health", False, f"Found {len(errors)} error(s). Symptoms: {', '.join(unique_errs[:3])}")
    except (PermissionError, OSError) as e:
        return _result("Log Health", False, f"Log file inaccessible: {e}")
    except Exception as e:
        return _result("Log Health", True, f"Scan skipped: {e}", warn=True)

def _check_system_env() -> list[dict[str, Any]]:
    import platform
    results = []
    results.append(_result("Platform", True, f"{platform.system()} {platform.release()} ({platform.machine()})"))
    results.append(_result("Python", True, sys.version.split()[0]))
    
    # Check for critical env vars
    roots = os.environ.get("SARI_WORKSPACE_ROOT")
    results.append(_result("Env: SARI_WORKSPACE_ROOT", bool(roots), roots or "Not set"))
    
    try:
        reg_path = str(get_registry_path())
        results.append(_result("Registry Path", True, reg_path))
        # Check if writable
        if os.path.exists(reg_path):
            if not os.access(reg_path, os.W_OK):
                results.append(_result("Registry Access", False, "Registry file is read-only"))
        elif not os.access(os.path.dirname(reg_path), os.W_OK):
            results.append(_result("Registry Access", False, "Registry directory is not writable"))
    except Exception as e:
        results.append(_result("Registry Path", False, f"Could not determine registry: {e}"))
    
    return results

def _check_process_resources(pid: int) -> dict[str, Any]:
    try:
        import psutil
        proc = psutil.Process(pid)
        with proc.oneshot():
            mem = proc.memory_info().rss / (1024 * 1024)
            cpu = proc.cpu_percent(interval=0.1)
            return {"mem_mb": round(mem, 1), "cpu_pct": cpu}
    except Exception:
        return {}

def _check_daemon() -> dict[str, Any]:
    host, port = get_daemon_address()
    identify = _identify_sari_daemon(host, port)
    running = identify is not None
    
    local_version = settings.VERSION
    details = {}
    
    if running:
        pid = read_pid()
        remote_version = identify.get("version", "unknown")
        draining = identify.get("draining", False)
        
        if pid:
            details = _check_process_resources(pid)
        
        status_msg = f"Running on {host}:{port} (PID: {pid}, v{remote_version})"
        if draining: status_msg += " [DRAINING]"
        if details:
            status_msg += f" [Mem: {details.get('mem_mb')}MB, CPU: {details.get('cpu_pct')}%]"
            
        if remote_version != local_version:
            return _result("Sari Daemon", False, f"Version mismatch: local=v{local_version}, remote=v{remote_version}. {status_msg}")
        
        return _result("Sari Daemon", True, status_msg)
    
    # Check for stale PID file
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, 0) # Signal 0 checks existence
            return _result("Sari Daemon", False, f"Not responding on {host}:{port} but PID {pid} is alive. Possible zombie or port conflict.")
        except (OSError, ProcessLookupError):
            return _result("Sari Daemon", False, f"Not running, but stale PID file exists (PID: {pid}).")
            
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
        elif name == "Workspace Overlap":
            recs.append({"name": name, "action": "Remove nested workspaces from MCP settings. Keep only the top-level root or the specific project roots."})
        elif name == "Windows Write Lock":
            recs.append({"name": name, "action": "On Windows, ensure msvcrt.locking is available and use a supported Python runtime."})
        elif name == "DB Migration Safety":
            recs.append({"name": name, "action": "Disable destructive migration paths; keep additive schema init/migrate strategy."})
        elif name == "Engine Sync DLQ":
            recs.append({"name": name, "action": "Run rescan/retry and verify engine is healthy until pending engine_sync_error tasks are cleared."})
        elif name == "Writer Health":
            recs.append({"name": name, "action": "If writer thread is dead, restart daemon and inspect DB/engine logs for the first failure."})
        elif name == "Storage Switch Guard":
            recs.append({"name": name, "action": "Restart process to clear blocked storage switch, then verify clean shutdown behavior."})
    return recs

def _auto_fixable(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for r in results:
        if r.get("passed"):
            continue
        name = str(r.get("name") or "")
        error = str(r.get("error") or "")
        
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
        elif name == "Sari Daemon" and "stale PID" in error:
            actions.append({"name": name, "action": "cleanup_pid"})
        elif name == "Sari Daemon" and "Version mismatch" in error:
            actions.append({"name": name, "action": "restart_daemon"})
    
    # Check for corrupted registry (SSOT Check)
    try:
        from sari.core.server_registry import ServerRegistry
        reg = ServerRegistry()
        data = reg._load()
        if not data or data.get("version") != ServerRegistry.VERSION:
             actions.append({"name": "Server Registry", "action": "repair_registry"})
    except Exception:
        actions.append({"name": "Server Registry", "action": "repair_registry"})
        
    return actions

def _run_auto_fixes(ws_root: str, actions: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not actions:
        return []
    results: list[dict[str, Any]] = []
    
    for action in actions:
        act = action["action"]
        name = action["name"]
        
        try:
            if act == "db_migrate":
                cfg_path = WorkspaceManager.resolve_config_path(ws_root)
                cfg = Config.load(cfg_path, workspace_root_override=ws_root)
                db = LocalSearchDB(cfg.db_path)
                db.close()
                results.append(_result(f"Auto Fix {name}", True, "Schema migration applied"))
            
            elif act == "cleanup_pid":
                from sari.mcp.cli import remove_pid
                pid_file = None
                try:
                    from sari.mcp.daemon import PID_FILE as _PID_FILE
                    pid_file = _PID_FILE
                except Exception:
                    pid_file = None
                try:
                    remove_pid()
                except Exception:
                    pass
                try:
                    if pid_file and pid_file.exists():
                        pid_file.unlink()
                except Exception:
                    pass
                try:
                    # Verify removal
                    if not pid_file or not pid_file.exists():
                        results.append(_result(f"Auto Fix {name}", True, "Stale PID file removed"))
                    else:
                        results.append(_result(f"Auto Fix {name}", False, "Failed to remove PID file - permission issue?"))
                except Exception as e:
                    results.append(_result(f"Auto Fix {name}", False, f"Cleanup error: {e}"))
                
            elif act == "repair_registry":
                from sari.core.server_registry import ServerRegistry
                reg = ServerRegistry()
                reg._save(reg._empty()) # Reset to clean state
                results.append(_result(f"Auto Fix {name}", True, "Corrupted registry file reset"))
                
            elif act == "restart_daemon":
                # Stop old one and suggest restart
                from sari.mcp.cli import cmd_daemon_stop
                class Args:
                    daemon_host = ""
                    daemon_port = None
                cmd_daemon_stop(Args())
                results.append(_result(f"Auto Fix {name}", True, "Incompatible daemon stopped. It will restart on next CLI use."))
                
        except Exception as e:
            results.append(_result(f"Auto Fix {name}", False, str(e)))
            
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


def _check_workspace_overlaps(ws_root: str) -> list[dict[str, Any]]:
    """Detect if multiple registered workspaces overlap, causing duplicate indexing."""
    results = []
    try:
        from sari.core.server_registry import ServerRegistry
        reg = ServerRegistry()
        data = reg._load()
        workspaces = list(data.get("workspaces", {}).keys())
        
        current = WorkspaceManager.normalize_path(ws_root)
        overlaps = []
        for ws in workspaces:
            norm_ws = WorkspaceManager.normalize_path(ws)
            if norm_ws == current: continue
            
            # Check if current is parent of ws or vice versa
            if current.startswith(norm_ws + os.sep) or norm_ws.startswith(current + os.sep):
                overlaps.append(norm_ws)
        
        if overlaps:
            results.append(_result(
                "Workspace Overlap", 
                False, 
                f"Nesting detected with: {', '.join(overlaps)}. This leads to duplicate indexing."
            ))
        else:
            results.append(_result("Workspace Overlap", True, "No nested roots detected"))
    except Exception as e:
        results.append(_result("Workspace Overlap Check", True, f"Skipped: {e}", warn=True))
    return results

def execute_doctor(args: Dict[str, Any], db: Any = None, logger: Any = None, roots: List[str] = None) -> Dict[str, Any]:
    ws_root = roots[0] if roots else WorkspaceManager.resolve_workspace_root()

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

    results.extend(_check_system_env())

    if include_venv:
        in_venv = sys.prefix != sys.base_prefix
        results.append(_result("Virtualenv", True, "" if in_venv else "Not running in venv (ok)"))

    if include_daemon:
        results.append(_check_daemon())
        results.append(_check_log_errors())

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
        results.append(_check_db_integrity(ws_root))
        results.extend(_check_db(ws_root))
        results.append(_check_db_migration_safety())
        results.append(_check_windows_write_lock_support())
        results.append(_check_engine_sync_dlq(ws_root))
        results.append(_check_embedded_engine_module())
        results.append(_check_engine_runtime(ws_root))
        results.append(_check_engine_tokenizer_data())
        results.append(_check_tree_sitter())
        results.append(_check_fts_rebuild_policy())
        results.append(_check_writer_health(db))
        results.append(_check_storage_switch_guard())

    if include_disk:
        results.append(_check_disk_space(ws_root, min_disk_gb))

    results.extend(_check_workspace_overlaps(ws_root))

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
        lines.append(pack_line("t", single_value=payload))
        return "\n".join(lines)

    return mcp_response(
        "doctor",
        build_pack,
        lambda: {"content": [{"type": "text", "text": payload}]},
    )
