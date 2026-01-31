import json
import os
import sys
import ipaddress
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_server_info() -> Optional[Dict]:
    """Load server.json if exists (single source of truth for actual port)."""
    root = _repo_root()
    server_json = root / "tools" / "local-search" / "data" / "server.json"
    if server_json.exists():
        try:
            with open(server_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _load_cfg() -> Dict:
    root = _repo_root()
    cfg_path = os.environ.get(
        "LOCAL_SEARCH_CONFIG",
        str(root / "tools" / "local-search" / "config" / "config.json"),
    )
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_host_port() -> Tuple[str, int]:
    """Get host/port from server.json (preferred) or config.json (fallback)."""
    server_info = _load_server_info()
    if server_info:
        return server_info.get("host", "127.0.0.1"), int(server_info.get("port", 47777))
    cfg = _load_cfg()
    return cfg.get("server_host", "127.0.0.1"), int(cfg.get("server_port", 47777))


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        # Non-IP hostnames are only allowed if explicitly localhost.
        return False


def _enforce_loopback(host: str) -> None:
    if os.environ.get("LOCAL_SEARCH_ALLOW_NON_LOOPBACK") == "1":
        return
    if not _is_loopback(host):
        raise RuntimeError(
            f"local-search loopback-only: server_host must be 127.0.0.1/localhost/::1 (got={host}). "
            "Set LOCAL_SEARCH_ALLOW_NON_LOOPBACK=1 to override (NOT recommended)."
        )


def _request(path: str, params: Dict) -> Dict:
    host, port = _get_host_port()

    _enforce_loopback(str(host))

    qs = urllib.parse.urlencode(params)
    url = f"http://{host}:{port}{path}?{qs}"
    with urllib.request.urlopen(url, timeout=3.0) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: query.py status|repo-candidates|search|rescan <q> [repo]", file=sys.stderr)
        return 2
    mode = argv[1]

    if mode == "status":
        try:
            data = _request("/status", {})
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if mode == "repo-candidates":
        if len(argv) < 3:
            print("missing q", file=sys.stderr)
            return 2
        q = argv[2]
        try:
            data = _request("/repo-candidates", {"q": q, "limit": 3})
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if mode == "search":
        if len(argv) < 3:
            print("missing q", file=sys.stderr)
            return 2
        q = argv[2]
        repo = argv[3] if len(argv) >= 4 else ""
        params = {"q": q, "limit": 10}
        if repo:
            params["repo"] = repo
        try:
            data = _request("/search", params)
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if mode == "rescan":
        try:
            data = _request("/rescan", {})
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
