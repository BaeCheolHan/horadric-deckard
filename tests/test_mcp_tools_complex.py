import os
import json
import pytest
import shutil
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
    
    # 1. Setup a real stale PID file for the doctor to find
    from sari.mcp.daemon import PID_FILE
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text("999999")
    
    # 2. Mock process existence check
    with patch("os.kill", side_effect=OSError), \
         patch("sari.mcp.cli.remove_pid", wraps=shutil.rmtree) as mock_remove:
        # Note: wraps=shutil.rmtree is a hack to make it a callable, 
        # let's just use a real side effect or verify via file existence
        
        # We need to mock _identify_sari_daemon to return None so it thinks daemon is NOT running
        # but PID file exists (stale state)
        with patch("sari.mcp.tools.doctor._cli_identify", return_value=None):
            resp = execute_doctor({"auto_fix": True, "include_network": False}, None, None, roots)
            
            # The doctor should have detected the stale PID and tried to fix it
            # Verify PID file is gone (doctor logic should have called remove_pid)
            assert not PID_FILE.exists()
            assert "Auto Fix Sari Daemon" in resp["content"][0]["text"]
