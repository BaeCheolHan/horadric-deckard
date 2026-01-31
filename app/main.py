import json
import os
import signal
import threading
import time
import ipaddress
from pathlib import Path
from datetime import datetime

# Support both `python3 app/main.py` (script mode) and package mode.
try:
    from .config import Config, resolve_config_path  # type: ignore
    from .db import LocalSearchDB  # type: ignore
    from .http_server import serve_forever  # type: ignore
    from .indexer import Indexer  # type: ignore
except ImportError:  # script mode
    from config import Config, resolve_config_path  # type: ignore
    from db import LocalSearchDB  # type: ignore
    from http_server import serve_forever  # type: ignore
    from indexer import Indexer  # type: ignore


def _repo_root() -> str:
    # file is .codex/tools/local-search/app/main.py
    return str(Path(__file__).resolve().parents[3])


def _detect_workspace_root() -> str:
    """Auto-detect workspace root (v2.3.2).
    
    Priority:
    1. LOCAL_SEARCH_WORKSPACE_ROOT env var
    2. Search for .codex-root from cwd upward
    3. Search for .codex-root from script location upward
    4. Fallback to _repo_root()
    """
    # 1. Environment variable
    env_root = os.environ.get("LOCAL_SEARCH_WORKSPACE_ROOT")
    if env_root and Path(env_root).exists():
        return str(Path(env_root).resolve())
    
    # 2. Search from cwd
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".codex-root").exists():
            return str(parent)
    
    # 3. Search from script location
    script_dir = Path(__file__).resolve().parent
    for parent in list(script_dir.parents):
        if (parent / ".codex-root").exists():
            return str(parent)
    
    # 4. Fallback
    return _repo_root()


def main() -> int:
    # v2.3.2: Auto-detect workspace root for HTTP fallback
    workspace_root = _detect_workspace_root()
    
    # Set env var so Config can pick it up
    os.environ["LOCAL_SEARCH_WORKSPACE_ROOT"] = workspace_root
    
    cfg_path = resolve_config_path(workspace_root)
    cfg = Config.load(cfg_path)

    # Security hardening: loopback-only by default.
    # Allow opt-in override only when explicitly requested.
    allow_non_loopback = os.environ.get("LOCAL_SEARCH_ALLOW_NON_LOOPBACK") == "1"
    host = (cfg.server_host or "127.0.0.1").strip()
    try:
        is_loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Non-IP hostnames are only allowed if they resolve to localhost explicitly.
        is_loopback = host.lower() == "localhost"

    if (not is_loopback) and (not allow_non_loopback):
        raise SystemExit(
            f"local-search refused to start: server_host must be loopback only (127.0.0.1/localhost/::1). got={host}. "
            "Set LOCAL_SEARCH_ALLOW_NON_LOOPBACK=1 to override (NOT recommended)."
        )

    # v2.4.1: Workspace-local DB path enforcement (multi-workspace support)
    # DB is ALWAYS stored within the workspace to prevent conflicts
    workspace_db_path = Path(workspace_root) / ".codex" / "tools" / "local-search" / "data" / "index.db"
    workspace_db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Debug override (only if explicitly set and not empty)
    debug_db_path = os.environ.get("LOCAL_SEARCH_DB_PATH", "").strip()
    if debug_db_path:
        print(f"[local-search] Using debug DB path override: {debug_db_path}")
        db_path = os.path.expanduser(debug_db_path)
    else:
        db_path = str(workspace_db_path)
    
    print(f"[local-search] DB path: {db_path}")

    db = LocalSearchDB(db_path)
    indexer = Indexer(cfg, db)

    # Start HTTP immediately so health checks don't block on initial indexing.
    # v2.3.3: serve_forever returns (httpd, actual_port) for fallback tracking
    httpd, actual_port = serve_forever(host, cfg.server_port, db, indexer)

    # Write server.json with actual binding info (single source of truth for port tracking)
    data_dir = Path(workspace_root) / ".codex" / "tools" / "local-search" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    server_json = data_dir / "server.json"
    server_info = {
        "host": host,
        "port": actual_port,  # v2.3.3: use actual bound port, not config port
        "config_port": cfg.server_port,  # original requested port for reference
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(),
    }
    server_json.write_text(json.dumps(server_info, indent=2), encoding="utf-8")
    
    if actual_port != cfg.server_port:
        print(f"[local-search] server.json updated with fallback port {actual_port}")

    stop_evt = threading.Event()

    def _shutdown(*_):
        if stop_evt.is_set():
            return
        stop_evt.set()
        try:
            indexer.stop()
        except Exception:
            pass
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Index in background.
    idx_thread = threading.Thread(target=indexer.run_forever, daemon=True)
    idx_thread.start()

    try:
        while not stop_evt.is_set():
            time.sleep(0.2)
    finally:
        _shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
