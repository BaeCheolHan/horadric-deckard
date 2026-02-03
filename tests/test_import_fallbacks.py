import importlib.util
import sys
import types
from pathlib import Path


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_fallback_imports():
    repo = Path(__file__).resolve().parents[1]
    app_dir = repo / "app"
    tools_dir = repo / "mcp" / "tools"
    sys.path.insert(0, str(app_dir))
    sys.path.insert(0, str(tools_dir))
    try:
        sys.modules["models"] = types.SimpleNamespace(SearchHit=object, SearchOptions=object)
        sys.modules["search_engine"] = types.SimpleNamespace(SqliteSearchEngineAdapter=object)
        sys.modules["engine_runtime"] = types.SimpleNamespace(EmbeddedEngine=object)
        _load(app_dir / "engine_registry.py", "engine_registry_fallback")
        _load(app_dir / "engine_runtime.py", "engine_runtime_fallback")
        _load(app_dir / "http_server.py", "http_server_fallback")

        for name in [
            "_util.py",
            "search.py",
            "status.py",
            "list_files.py",
            "read_file.py",
            "read_symbol.py",
            "repo_candidates.py",
            "index_file.py",
            "rescan.py",
            "scan_once.py",
            "doctor.py",
            "search_api_endpoints.py",
            "get_callers.py",
            "get_implementations.py",
            "search_symbols.py",
        ]:
            _load(tools_dir / name, f"tool_fallback_{name}")
    finally:
        for key in ["models", "search_engine", "engine_runtime"]:
            sys.modules.pop(key, None)
        if str(app_dir) in sys.path:
            sys.path.remove(str(app_dir))
        if str(tools_dir) in sys.path:
            sys.path.remove(str(tools_dir))
