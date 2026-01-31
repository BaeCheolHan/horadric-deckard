import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Support script mode and package mode
try:
    from .db import LocalSearchDB  # type: ignore
    from .indexer import Indexer  # type: ignore
except ImportError:
    from db import LocalSearchDB  # type: ignore
    from indexer import Indexer  # type: ignore


class Handler(BaseHTTPRequestHandler):
    # class attributes injected in `serve_forever`
    db: LocalSearchDB
    indexer: Indexer
    server_host: str = "127.0.0.1"
    server_port: int = 47777

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
                    "index_ready": bool(st.index_ready),
                    "last_scan_ts": st.last_scan_ts,
                    "scanned_files": st.scanned_files,
                    "indexed_files": st.indexed_files,
                    "errors": st.errors,
                    "fts_enabled": self.db.fts_enabled,
                }
            )

        if path == "/search":
            q = (qs.get("q") or [""])[0].strip()
            repo = (qs.get("repo") or [""])[0].strip() or None
            limit = int((qs.get("limit") or ["20"])[0])
            if not q:
                return self._json({"ok": False, "error": "missing q"}, status=400)
            hits, meta = self.db.search(
                q=q,
                repo=repo,
                limit=max(1, min(limit, 50)),
                snippet_max_lines=max(1, min(int(self.indexer.cfg.snippet_max_lines), 20)),
            )
            return self._json(
                {"ok": True, "q": q, "repo": repo, "meta": meta, "hits": [h.__dict__ for h in hits]}
            )

        if path == "/repo-candidates":
            q = (qs.get("q") or [""])[0].strip()
            limit = int((qs.get("limit") or ["3"])[0])
            if not q:
                return self._json({"ok": False, "error": "missing q"}, status=400)
            cands = self.db.repo_candidates(q=q, limit=max(1, min(limit, 5)))
            return self._json({"ok": True, "q": q, "candidates": cands})

        if path == "/rescan":
            # Trigger a scan ASAP (non-blocking)
            self.indexer.request_rescan()
            return self._json({"ok": True, "requested": True})

        return self._json({"ok": False, "error": "not found"}, status=404)


def serve_forever(host: str, port: int, db: LocalSearchDB, indexer: Indexer) -> tuple:
    """Start HTTP server with automatic port fallback on conflict (v2.3.2).
    
    Returns:
        tuple: (HTTPServer, actual_port) - actual_port may differ from requested port on fallback
    """
    import socket
    import sys
    
    # Bind dependencies as class attributes so they're available during __init__.
    class BoundHandler(Handler):
        pass

    BoundHandler.db = db  # type: ignore
    BoundHandler.indexer = indexer  # type: ignore
    BoundHandler.server_host = host  # type: ignore

    # v2.3.2: Try up to 10 ports on EADDRINUSE
    max_retries = 10
    actual_port = port
    httpd = None
    
    for attempt in range(max_retries):
        try:
            BoundHandler.server_port = actual_port  # type: ignore
            httpd = HTTPServer((host, actual_port), BoundHandler)
            break
        except socket.error as e:
            # EADDRINUSE or similar
            if attempt < max_retries - 1:
                print(f"[local-search] Port {actual_port} in use, trying {actual_port + 1}...", file=sys.stderr)
                actual_port += 1
            else:
                raise RuntimeError(f"Could not bind to any port ({port}-{actual_port}): {e}")
    
    if httpd is None:
        raise RuntimeError("Failed to create HTTP server")
    
    if actual_port != port:
        print(f"[local-search] Started on fallback port {actual_port} (original: {port})", file=sys.stderr)

    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return (httpd, actual_port)
