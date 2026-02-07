import os
import json
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from sari.core.db import LocalSearchDB
from sari.core.workspace import WorkspaceManager
from sari.mcp.tools.call_graph import execute_call_graph
from sari.mcp.tools.doctor import execute_doctor

@pytest.fixture
def complex_tool_context(tmp_path):
    root_path = tmp_path / "complex_ws"
    root_path.mkdir()
    
    db_path = root_path / "sari.db"
    db = LocalSearchDB(str(db_path))
    
    root_id = WorkspaceManager.root_id(str(root_path))
    db.upsert_root(root_id, str(root_path), str(root_path.resolve()), label="complex")
    
    # Setup Call Graph Data
    cur = db._write.cursor()
    files = [
        (f"{root_id}/a.py", "a.py", root_id, "repo", 100, 10, "def a(): b()", "h1", "a", 1000, 0, "ok", "", "ok", "", 0, 0, 0, 10, "{}"),
        (f"{root_id}/b.py", "b.py", root_id, "repo", 100, 10, "def b(): pass", "h2", "b", 1000, 0, "ok", "", "ok", "", 0, 0, 0, 10, "{}"),
    ]
    db.upsert_files_tx(cur, files)
    
    symbols = [
        ("sa", f"{root_id}/a.py", root_id, "a", "function", 1, 1, "def a()", "", "{}", "", "a"),
        ("sb", f"{root_id}/b.py", root_id, "b", "function", 1, 1, "def b()", "", "{}", "", "b"),
    ]
    db.upsert_symbols_tx(cur, symbols)
    
    relations = [
        (f"{root_id}/a.py", root_id, "a", "sa", f"{root_id}/b.py", root_id, "b", "sb", "calls", 1, "{}")
    ]
    db.upsert_relations_tx(cur, relations)
    db._write.commit()
    
    return {"db": db, "roots": [str(root_path)], "root_id": root_id, "path": root_path}

def test_call_graph_logic_integrity(complex_tool_context):
    db, roots = complex_tool_context["db"], complex_tool_context["roots"]
    # Standardized signature: (args, db, logger, roots)
    resp = execute_call_graph({"symbol": "a", "depth": 2}, db, MagicMock(), roots)
    text = resp["content"][0]["text"]
    assert "PACK1 tool=call_graph ok=true" in text
    assert "DOWNSTREAM" in text

def test_doctor_diagnostics_integrity(complex_tool_context):
    db, roots = complex_tool_context["db"], complex_tool_context["roots"]
    # Standardized signature: (args, db, logger, roots)
    resp = execute_doctor({"include_network": False}, db, MagicMock(), roots)
    text = resp["content"][0]["text"]
    assert "PACK1 tool=doctor ok=true" in text

def test_doctor_auto_fix_stale_pid(complex_tool_context, tmp_path):
    roots = complex_tool_context["roots"]

    from sari.core.server_registry import get_registry_path
    reg = get_registry_path()
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "version": "2.0",
        "daemons": {
            "boot-x": {
                "host": "127.0.0.1",
                "port": 47779,
                "pid": 999999,
                "start_ts": time.time(),
                "last_seen_ts": time.time(),
                "draining": False,
                "version": "0.0.0",
            }
        },
        "workspaces": {},
    }))

    with patch("os.kill", side_effect=OSError):
        with patch("sari.mcp.tools.doctor._cli_identify", return_value=None):
            resp = execute_doctor({"auto_fix": True, "include_network": False}, None, None, roots)
            assert "Auto Fix Sari Daemon" in resp["content"][0]["text"]
