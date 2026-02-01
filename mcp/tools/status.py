#!/usr/bin/env python3
"""
Status tool for Local Search MCP Server.
"""
import json
from typing import Any, Dict, Optional
from db import LocalSearchDB
from indexer import Indexer
from config import Config
from telemetry import TelemetryLogger


def execute_status(args: Dict[str, Any], indexer: Optional[Indexer], db: Optional[LocalSearchDB], cfg: Optional[Config], workspace_root: str, server_version: str, logger: Optional[TelemetryLogger] = None) -> Dict[str, Any]:
    """Execute status tool."""
    details = bool(args.get("details", False))
    
    status = {
        "index_ready": indexer.status.index_ready if indexer else False,
        "last_scan_ts": indexer.status.last_scan_ts if indexer else 0,
        "scanned_files": indexer.status.scanned_files if indexer else 0,
        "indexed_files": indexer.status.indexed_files if indexer else 0,
        "errors": indexer.status.errors if indexer else 0,
        "fts_enabled": db.fts_enabled if db else False,
        "workspace_root": workspace_root,
        "server_version": server_version,
    }
    
    # v2.5.2: Add config info for debugging
    if cfg:
        status["config"] = {
            "include_ext": cfg.include_ext,
            "exclude_dirs": cfg.exclude_dirs,
            "exclude_globs": getattr(cfg, "exclude_globs", []),
            "max_file_bytes": cfg.max_file_bytes,
        }
    
    if details and db:
        status["repo_stats"] = db.get_repo_stats()
    
    if logger:
        logger.log_telemetry(f"tool=status details={details} scanned={status['scanned_files']} indexed={status['indexed_files']}")
    
    return {
        "content": [{"type": "text", "text": json.dumps(status, indent=2)}],
    }
