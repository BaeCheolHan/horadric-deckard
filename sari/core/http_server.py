import json
import os
import threading
import mimetypes
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Support script mode and package mode
try:
    from .db import LocalSearchDB  # type: ignore
    from .indexer import Indexer  # type: ignore
    from .models import SearchOptions  # type: ignore
    from .http_middleware import run_http_middlewares, default_http_middlewares  # type: ignore
except ImportError:
    from db import LocalSearchDB  # type: ignore
    from indexer import Indexer  # type: ignore
    from models import SearchOptions  # type: ignore
    from http_middleware import run_http_middlewares, default_http_middlewares  # type: ignore


class Handler(BaseHTTPRequestHandler):
    # class attributes injected in `serve_forever`
    db: LocalSearchDB
    indexer: Indexer
    server_host: str = "127.0.0.1"
    server_port: int = 47777
    server_version: str = "dev"
    root_ids: list[str] = []
    mcp_server = None
    middlewares = default_http_middlewares()

    def _get_system_metrics(self):
        try:
            from sari.core.utils.system import get_system_metrics
            return get_system_metrics()
        except Exception:
            return {}

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _jsonrpc(self, obj, status=200):
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

        ctx = {"method": "GET", "path": path, "qs": qs, "headers": dict(self.headers)}
        def _exec():
            return self._handle_get(path, qs)
        resp = run_http_middlewares(ctx, self.middlewares, _exec)
        
        # If API returns 404, try serving static files
        if isinstance(resp, dict) and resp.get("status") == 404:
            if self._serve_static(path):
                return

        if isinstance(resp, dict):
            status = int(resp.pop("status", 200))
            return self._json(resp, status=status)
        return self._json({"ok": False, "error": "invalid response"}, status=500)

    def _serve_static(self, path: str) -> bool:
        """Serve static files from the 'static' directory."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        static_root = os.path.join(current_dir, "static")
        
        if path == "/":
            path = "/index.html"
            
        file_path = os.path.abspath(os.path.join(static_root, path.lstrip("/")))
        
        # Security: Prevent path traversal
        if not file_path.startswith(os.path.abspath(static_root)):
            return False

        if os.path.exists(file_path) and os.path.isfile(file_path):
            try:
                self.send_response(200)
                ctype, _ = mimetypes.guess_type(file_path)
                self.send_header("Content-Type", ctype or "application/octet-stream")
                
                with open(file_path, "rb") as f:
                    content = f.read()
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                return True
            except Exception:
                return False
        return False

    def _handle_get(self, path, qs):
        if path == "/health":
            return {"ok": True}

        if path == "/status":
            st = self.indexer.status
            repo_stats = self.db.get_repo_stats(root_ids=self.root_ids) if hasattr(self.db, "get_repo_stats") else {}
            total_db_files = sum(repo_stats.values()) if repo_stats else 0
            
            return {
                "ok": True,
                "host": self.server_host,
                "port": self.server_port,
                "version": self.server_version,
                "index_ready": bool(st.index_ready),
                "last_scan_ts": st.last_scan_ts,
                "last_commit_ts": self.indexer.get_last_commit_ts() if hasattr(self.indexer, "get_last_commit_ts") else 0,
                "scanned_files": st.scanned_files,
                "indexed_files": st.indexed_files,
                "total_files_db": total_db_files,
                "errors": st.errors,
                "fts_enabled": self.db.fts_enabled,
                "worker_count": getattr(self.indexer, "max_workers", 0),
                "performance": self.indexer.get_performance_metrics() if hasattr(self.indexer, "get_performance_metrics") else {},
                "queue_depths": self.indexer.get_queue_depths() if hasattr(self.indexer, "get_queue_depths") else {},
                "repo_stats": repo_stats,
                "roots": self.db.get_roots() if hasattr(self.db, "get_roots") else [],
                "system_metrics": self._get_system_metrics(),
                "config": {
                    "engine_mode": getattr(self.db.settings, "ENGINE_MODE", "unknown"),
                    "index_workers": getattr(self.indexer, "max_workers", 0),
                    "db_path": str(getattr(self.db, "db_path", "unknown")),
                    "log_level": getattr(self.db.settings, "LOG_LEVEL", "INFO"),
                    "fts_enabled": self.db.fts_enabled,
                    "http_port": self.server_port
                }
            }

        if path == "/doctor":
            try:
                from sari.core.health import SariDoctor
                doc = SariDoctor(workspace_root=getattr(self.indexer, "workspace_root", None))
                doc.run_all()
                return {"ok": True, "summary": doc.get_summary()}
            except Exception as e:
                return {"ok": False, "error": str(e), "status": 500}

        if path == "/daemon/list":
            try:
                from sari.core.utils.system import list_sari_processes
                return {"ok": True, "processes": list_sari_processes()}
            except Exception as e:
                return {"ok": False, "error": str(e), "status": 500}

        if path == "/graph":
            try:
                repo = qs.get("repo", [""])[0]
                if not repo: return {"ok": False, "error": "repo required", "status": 400}
                
                nodes = []
                edges = []
                
                with self.db._lock:
                    # 1. Fetch Symbols (Nodes)
                    cur = self.db._read.cursor()
                    cur.execute("SELECT symbol_id, name, kind, path FROM symbols WHERE path IN (SELECT path FROM files WHERE repo = ?)", (repo,))
                    rows = cur.fetchall()
                    
                    id_map = {} # path+name -> id
                    
                    for r in rows:
                        s_id, name, kind, f_path = r
                        # Simple Heuristic classification
                        role = "other"
                        lower_n = name.lower()
                        if "controller" in lower_n or "handler" in lower_n or "api" in lower_n: role = "controller"
                        elif "service" in lower_n or "manager" in lower_n: role = "service"
                        elif "repository" in lower_n or "dao" in lower_n or "store" in lower_n: role = "repository"
                        elif "model" in lower_n or "dto" in lower_n or "entity" in lower_n: role = "model"
                        
                        node_data = {
                            "data": {
                                "id": s_id or f"{f_path}::{name}", 
                                "label": name, 
                                "kind": kind, 
                                "role": role,
                                "path": f_path
                            }
                        }
                        nodes.append(node_data)
                        id_map[f"{f_path}::{name}"] = node_data["data"]["id"]

                    # 2. Fetch Relations (Edges)
                    # Note: Using JOIN to filter by repo is better, but simplified here
                    cur.execute("""
                        SELECT from_symbol_id, to_symbol_id, rel_type 
                        FROM symbol_relations 
                        WHERE from_path IN (SELECT path FROM files WHERE repo = ?)
                    """, (repo,))
                    rels = cur.fetchall()
                    
                    for rel in rels:
                        src, target, rtype = rel
                        if src and target:
                            edges.append({"data": {"source": src, "target": target, "label": rtype}})

                return {"ok": True, "elements": {"nodes": nodes, "edges": edges}}
            except Exception as e:
                return {"ok": False, "error": str(e), "status": 500}

        if path == "/search":
            q = (qs.get("q") or [""])[0].strip()
            repo = (qs.get("repo") or [""])[0].strip() or None
            try:
                limit = int((qs.get("limit") or ["20"])[0])
            except (ValueError, TypeError):
                limit = 20
            total_mode = (qs.get("total_mode") or [""])[0].strip().lower()
            root_ids = qs.get("root_ids") or []
            if not q:
                return {"ok": False, "error": "missing q", "status": 400}
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
                            return {"ok": False, "error": "engine not installed", "hint": "sari --cmd engine install", "status": 503}
                        if hasattr(engine, "install"):
                            try:
                                engine.install()
                                st = engine.status()
                                engine_mode = st.engine_mode
                                index_version = st.index_version
                            except Exception as e:
                                return {"ok": False, "error": f"engine install failed: {e}", "hint": "sari --cmd engine install", "status": 503}
                    if engine_mode == "embedded" and not st.engine_ready:
                        return {"ok": False, "error": f"engine_ready=false reason={st.reason}", "hint": st.hint, "status": 503}
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
                        return {"ok": False, "error": "root_ids out of scope", "status": 400}
            try:
                snippet_lines = max(1, min(int(self.indexer.cfg.snippet_max_lines), 20))
            except (ValueError, TypeError, AttributeError):
                snippet_lines = 3
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
                return {"ok": False, "error": f"engine query failed: {e}", "status": 500}
            return {"ok": True, "q": q, "repo": repo, "meta": meta, "engine": engine_mode, "index_version": index_version, "hits": [h.__dict__ for h in hits]}

        if path == "/repo-candidates":
            q = (qs.get("q") or [""])[0].strip()
            try:
                limit = int((qs.get("limit") or ["3"])[0])
            except (ValueError, TypeError):
                limit = 3
            if not q:
                return {"ok": False, "error": "missing q", "status": 400}
            cands = self.db.repo_candidates(q=q, limit=max(1, min(limit, 5)), root_ids=self.root_ids)
            return {"ok": True, "q": q, "candidates": cands}

        if path == "/rescan":
            # Trigger a scan ASAP (non-blocking)
            self.indexer.request_rescan()
            return {"ok": True, "requested": True}

        return {"ok": False, "error": "not found", "status": 404}

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/roots/remove":
            # ... (기존 로직 유지)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                root_id = payload.get("root_id")
                if not root_id:
                    return self._json({"ok": False, "error": "missing root_id"}, status=400)
                with self.db._lock:
                    self.db._write.execute("DELETE FROM roots WHERE root_id = ?", (root_id,))
                    self.db._write.commit()
                return {"ok": True, "removed": root_id}
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, status=500)

        if path == "/daemon/kill":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                pid = payload.get("pid")
                all_stale = payload.get("stale", False)
                
                from sari.core.utils.system import kill_sari_process, list_sari_processes
                if all_stale:
                    procs = list_sari_processes()
                    killed = []
                    for p in procs:
                        if not p['is_self']:
                            if kill_sari_process(p['pid']): killed.append(p['pid'])
                    return {"ok": True, "killed": killed}
                
                if pid and kill_sari_process(int(pid)):
                    return {"ok": True, "killed": [pid]}
                return self._json({"ok": False, "error": "failed to kill"}, status=400)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, status=500)

        if path != "/mcp":
            return self._json({"ok": False, "error": "not found"}, status=404)

        if self.mcp_server is None:
            return self._jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32000, "message": "MCP-over-HTTP is not enabled"},
                },
                status=503,
            )

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        if length <= 0:
            return self._jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Empty request body"},
                },
                status=400,
            )

        body = self.rfile.read(length)
        if not body:
            return self._jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Empty request body"},
                },
                status=400,
            )

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return self._jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
                status=400,
            )

        def _handle_one(req):
            if not isinstance(req, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
            return self.mcp_server.handle_request(req)

        if isinstance(payload, list):
            responses = []
            for item in payload:
                resp = _handle_one(item)
                if resp is not None:
                    responses.append(resp)
            if not responses:
                self.send_response(204)
                self.end_headers()
                return
            return self._jsonrpc(responses, status=200)

        response = _handle_one(payload)
        if response is None:
            self.send_response(204)
            self.end_headers()
            return
        return self._jsonrpc(response, status=200)


def serve_forever(host: str, port: int, db: LocalSearchDB, indexer: Indexer, version: str = "dev", workspace_root: str = "", cfg=None, mcp_server=None) -> tuple:
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
    BoundHandler.mcp_server = mcp_server  # type: ignore
    try:
        from sari.core.workspace import WorkspaceManager
        BoundHandler.root_ids = [WorkspaceManager.root_id_for_workspace(r) for r in indexer.cfg.workspace_roots]  # type: ignore
    except Exception:
        BoundHandler.root_ids = []  # type: ignore

    if BoundHandler.mcp_server is None:
        try:
            from sari.mcp.server import LocalSearchMCPServer
            if cfg is not None:
                BoundHandler.mcp_server = LocalSearchMCPServer(workspace_root, cfg=cfg, db=db, indexer=indexer)  # type: ignore
            else:
                BoundHandler.mcp_server = LocalSearchMCPServer(workspace_root)  # type: ignore
        except Exception:
            BoundHandler.mcp_server = None  # type: ignore

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

    if actual_port != port:
        print(f"[sari] HTTP API started on port {actual_port} (requested: {port})", file=sys.stderr)

    # Smart Browser Open: Focus/Reload existing tab instead of opening many windows
    auto_open = (os.environ.get("SARI_HTTP_AUTO_OPEN", "1").strip().lower() in {"1", "true", "yes", "on"})
    if auto_open:
        def _smart_open():
            import subprocess
            import sys
            import time
            
            url = f"http://{host}:{actual_port}/"
            # Throttling: Don't open if we opened one in the last 10 seconds (prevents rapid restart spam)
            tmp_marker = os.path.join(os.path.expanduser("~"), ".sari_last_open")
            now = time.time()
            if os.path.exists(tmp_marker):
                try:
                    if now - os.path.getmtime(tmp_marker) < 10: return
                except Exception: pass
            Path(tmp_marker).touch()

            if sys.platform == "darwin":
                # AppleScript to find and reload Sari tab in Chrome or Safari
                script = f'''
                set found to false
                try
                    tell application "Google Chrome"
                        repeat with w in windows
                            repeat with t in tabs of w
                                if URL of t contains "localhost:{actual_port}" then
                                    reload t
                                    set index of w to 1
                                    set active tab index of w to (get id of t)
                                    set found to true
                                    exit repeat
                                end if
                            end repeat
                            if found then exit repeat
                        end repeat
                    end tell
                end try
                if found is false then
                    try
                        tell application "Safari"
                            repeat with w in windows
                                repeat with t in tabs of w
                                    if URL of t contains "localhost:{actual_port}" then
                                        tell t to set its URL to "{url}"
                                        set index of w to 1
                                        set found to true
                                        exit repeat
                                    end if
                                end repeat
                                if found then exit repeat
                            end repeat
                        end tell
                    end try
                end if
                if found is false then do shell script "open " & quoted form of "{url}"
                '''
                subprocess.run(["osascript", "-e", script], capture_output=True)
            else:
                import webbrowser
                webbrowser.open(url)

        threading.Timer(0.8, _smart_open).start()

    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return (httpd, actual_port)
