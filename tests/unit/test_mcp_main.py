import runpy
import types
import sys

import pytest


def test_main_routes_to_cli(monkeypatch):
    sys.modules.pop("mcp.__main__", None)
    orig_server = sys.modules.get("mcp.server")
    orig_cli = sys.modules.get("mcp.cli")
    monkeypatch.setattr(sys, "argv", ["-m", "mcp", "daemon"])
    import types
    dummy_cli = types.SimpleNamespace(main=lambda: 0)
    sys.modules["mcp.cli"] = dummy_cli
    sys.modules["mcp.server"] = types.SimpleNamespace(main=lambda: None)
    runpy.run_module("mcp.__main__", run_name="__main__")
    if orig_server is not None:
        sys.modules["mcp.server"] = orig_server
    else:
        sys.modules.pop("mcp.server", None)
    if orig_cli is not None:
        sys.modules["mcp.cli"] = orig_cli
    else:
        sys.modules.pop("mcp.cli", None)


def test_main_routes_to_server(monkeypatch):
    sys.modules.pop("mcp.__main__", None)
    orig_server = sys.modules.get("mcp.server")
    monkeypatch.setattr(sys, "argv", ["-m", "mcp"])
    import types
    sys.modules["mcp.server"] = types.SimpleNamespace(main=lambda: None)
    runpy.run_module("mcp.__main__", run_name="__main__")
    if orig_server is not None:
        sys.modules["mcp.server"] = orig_server
    else:
        sys.modules.pop("mcp.server", None)
