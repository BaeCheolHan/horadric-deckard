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
    from . import config as config_mod  # type: ignore
    from .db import LocalSearchDB  # type: ignore
    from .http_server import serve_forever  # type: ignore
    from .indexer import Indexer  # type: ignore
    from .workspace import WorkspaceManager  # type: ignore
except ImportError:  # script mode
    from config import Config, resolve_config_path  # type: ignore
    import config as config_mod  # type: ignore
    from db import LocalSearchDB  # type: ignore
    from http_server import serve_forever  # type: ignore
    from indexer import Indexer  # type: ignore
    from workspace import WorkspaceManager  # type: ignore


def _repo_root() -> str:
    # Fallback to current working directory if not running from a nested structure
    return str(Path.cwd())


def main() -> int:
    # v2.3.2: Auto-detect workspace root for HTTP fallback
    workspace_root = WorkspaceManager.resolve_workspace_root()
    
    # Set env var so Config can pick it up
    os.environ["LOCAL_SEARCH_WORKSPACE_ROOT"] = workspace_root
    
    cfg_path = resolve_config_path(workspace_root)
    
    # Graceful config loading (Global Install Support)
    if os.path.exists(cfg_path):
        cfg = Config.load(cfg_path)
    else:
        # Use safe defaults if config.json is missing.
        print(f"[deckard] Config not found in workspace ({cfg_path}), using defaults.")
        defaults = config_mod.Config.get_defaults(workspace_root)
        cfg = Config(**defaults)


    # Security hardening: loopback-only by default.
    # Allow opt-in override only when explicitly requested.
    allow_non_loopback = os.environ.get("LOCAL_SEARCH_ALLOW_NON_LOOPBACK") == "1"
    host = (cfg.http_api_host or "127.0.0.1").strip()
    try:
        is_loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Non-IP hostnames are only allowed if they resolve to localhost explicitly.
        is_loopback = host.lower() == "localhost"

    if (not is_loopback) and (not allow_non_loopback):
        raise SystemExit(
            f"deckard refused to start: server_host must be loopback only (127.0.0.1/localhost/::1). got={host}. "
            "Set LOCAL_SEARCH_ALLOW_NON_LOOPBACK=1 to override (NOT recommended)."
        )

    # v2.4.1: Workspace-local DB path enforcement (multi-workspace support)
    # DB path is now determined by Config.load
    db_path = cfg.db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    print(f"[deckard] DB path: {db_path}")

    db = LocalSearchDB(db_path)
    from app.indexer import resolve_indexer_settings
    mode, enabled, startup_enabled, lock_handle = resolve_indexer_settings(str(db_path))
    indexer = Indexer(cfg, db, indexer_mode=mode, indexing_enabled=enabled, startup_index_enabled=startup_enabled, lock_handle=lock_handle)

    # Start HTTP immediately so health checks don't block on initial indexing.
    # v2.3.3: serve_forever returns (httpd, actual_port) for fallback tracking
    version = os.environ.get("DECKARD_VERSION", "dev")
    httpd, actual_port = serve_forever(host, cfg.http_api_port, db, indexer, version=version, workspace_root=workspace_root)

    # Write server.json with actual binding info (single source of truth for port tracking)
    data_dir = Path(workspace_root) / ".codex" / "tools" / "deckard" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    server_json = data_dir / "server.json"
    server_info = {
        "host": host,
        "port": actual_port,  # v2.3.3: use actual bound port, not config port
        "config_port": cfg.http_api_port,  # original requested port for reference
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(),
    }
    server_json.write_text(json.dumps(server_info, indent=2), encoding="utf-8")

    if actual_port != cfg.http_api_port:
        print(f"[deckard] server.json updated with fallback port {actual_port}")

    try:
        port_file = Path(db_path + ".http_api.port")
        port_file.write_text(str(actual_port) + "\n", encoding="utf-8")
    except Exception:
        pass

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
