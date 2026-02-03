#!/usr/bin/env python3
"""
Status tool for Local Search MCP Server.
"""
from typing import Any, Dict, Optional
from mcp.tools._util import mcp_response, pack_header, pack_line, resolve_root_ids

try:
    from app.db import LocalSearchDB
    from app.indexer import Indexer
    from app.config import Config
    from app.registry import ServerRegistry
    from mcp.telemetry import TelemetryLogger
except ImportError:
    # Fallback for direct script execution
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.db import LocalSearchDB
    from app.indexer import Indexer
    from app.config import Config
    from app.registry import ServerRegistry
    from mcp.telemetry import TelemetryLogger


def execute_status(args: Dict[str, Any], indexer: Optional[Indexer], db: Optional[LocalSearchDB], cfg: Optional[Config], workspace_root: str, server_version: str, logger: Optional[TelemetryLogger] = None) -> Dict[str, Any]:
    """Execute status tool."""
    details = bool(args.get("details", False))
    
    # 1. Gather status data
    actual_http_port = None
    try:
        inst = ServerRegistry().get_instance(workspace_root)
        if inst and inst.get("port"):
            actual_http_port = int(inst.get("port"))
    except Exception:
        actual_http_port = None

    config_http_port = cfg.http_api_port if cfg else 0
    status_data = {
        "index_ready": indexer.status.index_ready if indexer else False,
        "last_scan_ts": indexer.status.last_scan_ts if indexer else 0,
        "last_commit_ts": indexer.get_last_commit_ts() if indexer and hasattr(indexer, "get_last_commit_ts") else 0,
        "scanned_files": indexer.status.scanned_files if indexer else 0,
        "indexed_files": indexer.status.indexed_files if indexer else 0,
        "errors": indexer.status.errors if indexer else 0,
        "fts_enabled": db.fts_enabled if db else False,
        "workspace_root": workspace_root,
        "server_version": server_version,
        "http_api_port": actual_http_port if actual_http_port is not None else config_http_port,
        "http_api_port_config": config_http_port,
        "indexer_mode": getattr(indexer, "indexer_mode", "auto") if indexer else "off",
    }
    if db and hasattr(db, "engine") and hasattr(db.engine, "status"):
        try:
            st = db.engine.status()
            status_data.update({
                "engine_mode": st.engine_mode,
                "engine_ready": st.engine_ready,
                "engine_version": st.engine_version,
                "index_docs": st.doc_count,
                "index_size_bytes": st.index_size_bytes,
                "last_build_ts": st.last_build_ts,
                "engine_reason": st.reason,
                "engine_hint": st.hint,
                "engine_mem_mb": getattr(st, "engine_mem_mb", 0),
                "index_mem_mb": getattr(st, "index_mem_mb", 0),
                "engine_threads": getattr(st, "engine_threads", 0),
            })
        except Exception:
            status_data.update({
                "engine_mode": "embedded",
                "engine_ready": False,
            })
    if indexer and hasattr(indexer, "get_queue_depths"):
        status_data["queue_depths"] = indexer.get_queue_depths()
    
    if cfg:
        status_data["config"] = {
            "include_ext": cfg.include_ext,
            "exclude_dirs": cfg.exclude_dirs,
            "exclude_globs": getattr(cfg, "exclude_globs", []),
            "max_file_bytes": cfg.max_file_bytes,
            "http_api_port": cfg.http_api_port,
        }
    
    repo_stats = None
    if details and db:
        root_ids = resolve_root_ids(cfg.workspace_roots if cfg else [])
        repo_stats = db.get_repo_stats(root_ids=root_ids)
        status_data["repo_stats"] = repo_stats
    
    if logger:
        logger.log_telemetry(f"tool=status details={details} scanned={status_data['scanned_files']} indexed={status_data['indexed_files']}")

    # --- JSON Builder ---
    def build_json() -> Dict[str, Any]:
        return status_data

    # --- PACK1 Builder ---
    def build_pack() -> str:
        metrics = []
        
        # Base status
        for k, v in status_data.items():
            if k in {"config", "repo_stats", "queue_depths"}:
                continue
            val = str(v).lower() if isinstance(v, bool) else str(v)
            metrics.append((k, val))
            
        # Config (if exists)
        if "config" in status_data:
            c = status_data["config"]
            metrics.append(("cfg_include_ext", ",".join(c.get("include_ext", []))))
            metrics.append(("cfg_max_file_bytes", str(c.get("max_file_bytes", 0))))

        if "queue_depths" in status_data:
            q = status_data["queue_depths"]
            metrics.append(("queue_watcher", str(q.get("watcher", 0))))
            metrics.append(("queue_db_writer", str(q.get("db_writer", 0))))
            metrics.append(("queue_telemetry", str(q.get("telemetry", 0))))
            
        # Repo stats (if exists)
        if repo_stats:
            for r_name, r_count in repo_stats.items():
                metrics.append((f"repo_{r_name}", str(r_count)))
                
        # Build lines
        lines = [pack_header("status", {}, returned=len(metrics))]
        for k, v in metrics:
            lines.append(pack_line("m", kv={k: v}))
            
        return "\n".join(lines)

    return mcp_response("status", build_pack, build_json)
