import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Support script mode and package mode
try:
    from .db import LocalSearchDB  # type: ignore
    from .indexer import Indexer  # type: ignore
    from .models import SearchOptions  # type: ignore
except ImportError:
    from db import LocalSearchDB  # type: ignore
    from indexer import Indexer  # type: ignore
    from models import SearchOptions  # type: ignore


class Handler(BaseHTTPRequestHandler):
    # class attributes injected in `serve_forever`
    db: LocalSearchDB
    indexer: Indexer
    server_host: str = "127.0.0.1"
    server_port: int = 47777
    server_version: str = "dev"
    root_ids: list[str] = []

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # keep logs quiet
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/health":
            return self._json({"ok": True})

        if path == "/status":
            st = self.indexer.status
            return self._json(
                {
                    "ok": True,
                    "host": self.server_host,
                    "port": self.server_port,
                    "version": self.server_version,
                    "index_ready": bool(st.index_ready),
                    "last_scan_ts": st.last_scan_ts,
                    "last_commit_ts": self.indexer.get_last_commit_ts() if hasattr(self.indexer, "get_last_commit_ts") else 0,
                    "scanned_files": st.scanned_files,
                    "indexed_files": st.indexed_files,
                    "errors": st.errors,
                    "fts_enabled": self.db.fts_enabled,
                    "queue_depths": self.indexer.get_queue_depths() if hasattr(self.indexer, "get_queue_depths") else {},
                }
            )

        if path == "/search":
            q = (qs.get("q") or [""])[0].strip()
            repo = (qs.get("repo") or [""])[0].strip() or None
            limit = int((qs.get("limit") or ["20"])[0])
            total_mode = (qs.get("total_mode") or [""])[0].strip().lower()
            root_ids = qs.get("root_ids") or []
            if not q:
                return self._json({"ok": False, "error": "missing q"}, status=400)
            engine = getattr(self.db, "engine", None)
            engine_mode = "sqlite"
            index_version = ""
            if engine and hasattr(engine, "status"):
                st = engine.status()
                engine_mode = st.engine_mode
                index_version = st.index_version
                if engine_mode == "embedded" and not st.engine_ready:
                    if st.reason == "NOT_INSTALLED":
                        auto_install = (os.environ.get("SARI_ENGINE_AUTO_INSTALL", "1").strip().lower() not in {"0", "false", "no", "off"})
                        if not auto_install:
                            return self._json({"ok": False, "error": "engine not installed", "hint": "sari --cmd engine install"}, status=503)
                        if hasattr(engine, "install"):
                            try:
                                engine.install()
                                st = engine.status()
                                engine_mode = st.engine_mode
                                index_version = st.index_version
                            except Exception as e:
                                return self._json({"ok": False, "error": f"engine install failed: {e}", "hint": "sari --cmd engine install"}, status=503)
                    if engine_mode == "embedded" and not st.engine_ready:
                        return self._json({"ok": False, "error": f"engine_ready=false reason={st.reason}", "hint": st.hint}, status=503)
            req_root_ids: list[str] = []
            for item in root_ids:
                if "," in item:
                    req_root_ids.extend([r for r in item.split(",") if r])
                elif item:
                    req_root_ids.append(item)
            allowed = list(self.root_ids or [])
            final_root_ids = allowed
            if req_root_ids:
                final_root_ids = [r for r in allowed if r in req_root_ids]
                if req_root_ids and not final_root_ids:
                    if self.db.has_legacy_paths():
                        final_root_ids = []
                    else:
                        return self._json({"ok": False, "error": "root_ids out of scope"}, status=400)
            snippet_lines = max(1, min(int(self.indexer.cfg.snippet_max_lines), 20))
            opts = SearchOptions(
                query=q,
                repo=repo,
                limit=max(1, min(limit, 50)),
                snippet_lines=snippet_lines,
                root_ids=final_root_ids,
                total_mode=total_mode if total_mode in {"exact", "approx"} else "exact",
            )
            try:
                hits, meta = self.db.search_v2(opts)
            except Exception as e:
                return self._json({"ok": False, "error": f"engine query failed: {e}"}, status=500)
            return self._json(
                {"ok": True, "q": q, "repo": repo, "meta": meta, "engine": engine_mode, "index_version": index_version, "hits": [h.__dict__ for h in hits]}
            )

        if path == "/repo-candidates":
            q = (qs.get("q") or [""])[0].strip()
            limit = int((qs.get("limit") or ["3"])[0])
            if not q:
                return self._json({"ok": False, "error": "missing q"}, status=400)
            cands = self.db.repo_candidates(q=q, limit=max(1, min(limit, 5)), root_ids=self.root_ids)
            return self._json({"ok": True, "q": q, "candidates": cands})

        if path == "/rescan":
            # Trigger a scan ASAP (non-blocking)
            self.indexer.request_rescan()
            return self._json({"ok": True, "requested": True})

        return self._json({"ok": False, "error": "not found"}, status=404)


def serve_forever(host: str, port: int, db: LocalSearchDB, indexer: Indexer, version: str = "dev", workspace_root: str = "") -> tuple:
    """Start HTTP server with Registry-based port allocation.

    Returns:
        tuple: (HTTPServer, actual_port)
    """
    import socket
    import sys
    import os

    # Try importing registry, fallback if missing
    try:
        from .registry import ServerRegistry  # type: ignore
        registry = ServerRegistry()
        has_registry = True
    except ImportError:
        registry = None
        has_registry = False

    # Bind dependencies as class attributes
    class BoundHandler(Handler):
        pass

    BoundHandler.db = db  # type: ignore
    BoundHandler.indexer = indexer  # type: ignore
    BoundHandler.server_host = host  # type: ignore
    BoundHandler.server_version = version  # type: ignore
    try:
        from sari.core.workspace import WorkspaceManager
        BoundHandler.root_ids = [WorkspaceManager.root_id(r) for r in indexer.cfg.workspace_roots]  # type: ignore
    except Exception:
        BoundHandler.root_ids = []  # type: ignore

    strategy = (os.environ.get("SARI_HTTP_API_PORT_STRATEGY") or "auto").strip().lower()
    actual_port = port
    httpd = None
    try:
        BoundHandler.server_port = actual_port  # type: ignore
        httpd = ThreadingHTTPServer((host, actual_port), BoundHandler)
    except OSError as e:
        if strategy == "strict":
            raise RuntimeError(f"HTTP API port {actual_port} unavailable: {e}")
        # auto strategy: retry with port=0 (OS-assigned)
        try:
            BoundHandler.server_port = 0  # type: ignore
            httpd = ThreadingHTTPServer((host, 0), BoundHandler)
            actual_port = httpd.server_address[1]
        except OSError:
            raise RuntimeError("Failed to create HTTP server")

    if httpd is None:
        raise RuntimeError("Failed to create HTTP server")

    actual_port = httpd.server_address[1]
    BoundHandler.server_port = actual_port  # type: ignore

    # Register in server.json
    if has_registry and workspace_root:
        try:
            registry.register(workspace_root, actual_port, os.getpid())
        except Exception as e:
            print(f"[sari] Registry update failed: {e}", file=sys.stderr)

    if actual_port != port:
        print(f"[sari] HTTP API started on port {actual_port} (requested: {port})", file=sys.stderr)

    # Clean shutdown hook?
    # HTTP Server runs in thread, so unregistering is tricky if main thread dies hard.
    # But serve_forever is called in thread usually.
    # The caller (mcp.server) is responsible for unregistering OR we trust 'pid' check.
    # Let's rely on PID check for now (lazy cleanup), but try to unregister if possible.

    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return (httpd, actual_port)
