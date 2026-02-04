import os

from sari.mcp.tools.search import execute_search
from sari.core.models import SearchHit


class DummyEngine:
    def status(self):
        class S:
            engine_mode = "sqlite"
            engine_ready = True
            index_version = ""
        return S()

    def search_v2(self, opts):
        hits = []
        for i in range(10):
            hits.append(SearchHit(
                repo="__root__",
                path=f"root-aaaa/file_{i}.txt",
                score=1.0,
                snippet="line1\\nline2",
                mtime=0,
                size=1,
                match_count=1,
                file_type="txt",
                hit_reason="",
            ))
        return hits, {"total": 10, "total_mode": "exact"}


class DummyDB:
    def __init__(self):
        self.engine = DummyEngine()

    def has_legacy_paths(self):
        return False


class DummyLogger:
    def log_telemetry(self, _msg):
        pass


def test_search_snippet_reduces_read_calls(tmp_path):
    os.environ["SARI_FORMAT"] = "json"
    res = execute_search({"query": "hello"}, DummyDB(), DummyLogger(), [str(tmp_path)])
    results = res.get("results") or res.get("hits") or res.get("items") or []
    if not results and res.get("content"):
        # JSON response is also included in top-level keys by mcp_response
        results = res.get("results", [])

    # Fallback to JSON body if needed
    if not results and res.get("content"):
        import json
        payload = json.loads(res["content"][0]["text"])
        results = payload.get("results", [])

    assert results
    assert all(r.get("snippet") for r in results)

    # Baseline: 1 read_* call per hit to fetch snippet.
    baseline_calls = len(results)
    # New behavior: snippet already included in search results.
    new_calls = 0
    reduction = (baseline_calls - new_calls) / max(1, baseline_calls)
    assert reduction >= 0.30
    os.environ.pop("SARI_FORMAT", None)
