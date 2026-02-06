import os
import json
import pytest
import shutil
import time
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock
from sari.core.db import LocalSearchDB
from sari.core.workspace import WorkspaceManager
from sari.mcp.tools.search import execute_search
from sari.mcp.tools.search_symbols import execute_search_symbols
from sari.mcp.tools.list_files import execute_list_files
from sari.mcp.tools.read_file import execute_read_file
from sari.mcp.tools.read_symbol import execute_read_symbol
from sari.mcp.tools.status import execute_status
from sari.mcp.tools.repo_candidates import execute_repo_candidates
from sari.mcp.tools.scan_once import execute_scan_once
from sari.mcp.tools.rescan import execute_rescan
from sari.mcp.tools.get_snippet import execute_get_snippet

@pytest.fixture
def tool_context(tmp_path):
    """Provides a realistic environment for tool testing."""
    root_path = tmp_path / "test_ws"
    root_path.mkdir()
    
    db_path = root_path / "sari.db"
    db = LocalSearchDB(str(db_path))
    
    # 1. Setup Root
    root_id = WorkspaceManager.root_id(str(root_path))
    db.upsert_root(root_id, str(root_path), str(root_path.resolve()), label="test")
    
    # 2. Setup Files
    files = [
        (f"{root_id}/main.py", "main.py", root_id, "repo1", 100, 50, "def hello():\n    pass", "h1", "hello", 1000, 0, "ok", "", "ok", "", 0, 0, 0, 50, "{}"),
        (f"{root_id}/util.js", "util.js", root_id, "repo1", 100, 30, "function add() {}", "h2", "add", 1000, 0, "ok", "", "ok", "", 0, 0, 0, 30, "{}"),
    ]
    cur = db._write.cursor()
    db.upsert_files_tx(cur, files)
    
    # 3. Setup Symbols
    symbols = [
        ("s1", f"{root_id}/main.py", root_id, "hello", "function", 1, 2, "def hello():", "", "{}", "", "hello"),
        ("s2", f"{root_id}/util.js", root_id, "add", "function", 1, 1, "function add()", "", "{}", "", "add"),
    ]
    db.upsert_symbols_tx(cur, symbols)
    db._write.commit()
    
    logger = MagicMock()
    return {
        "db": db,
        "roots": [str(root_path)],
        "root_id": root_id,
        "logger": logger,
        "path": root_path
    }

def test_search_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    # Logic is standard: query is required
    resp = execute_search({"query": "hello", "limit": 5}, db, tool_context["logger"], roots)
    text = resp["content"][0]["text"]
    assert "PACK1 tool=search ok=true" in text
    # Should find util.js because of 'add' snippet or path
    # Actually, searching 'hello' should find main.py
    assert "main.py" in urllib.parse.unquote(text)

def test_search_symbols_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    resp = execute_search_symbols({"query": "hello"}, db, tool_context["logger"], roots)
    text = resp["content"][0]["text"]
    assert "PACK1 tool=search_symbols ok=true" in text
    assert "name=hello" in text

def test_list_files_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    resp_sum = execute_list_files({}, db, tool_context["logger"], roots)
    assert "mode=summary" in resp_sum["content"][0]["text"]
    resp_det = execute_list_files({"repo": "repo1"}, db, tool_context["logger"], roots)
    assert "main.py" in urllib.parse.unquote(resp_det["content"][0]["text"])

def test_read_file_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    root_id = tool_context["root_id"]
    # PACK1 encodes everything. We must decode to verify business content.
    resp1 = execute_read_file({"path": f"{root_id}/main.py"}, db, roots)
    decoded = urllib.parse.unquote(resp1["content"][0]["text"])
    assert "def hello" in decoded
    
    fs_path = str(tool_context["path"] / "main.py")
    resp2 = execute_read_file({"path": fs_path}, db, roots)
    assert "def hello" in urllib.parse.unquote(resp2["content"][0]["text"])

def test_read_symbol_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    root_id = tool_context["root_id"]
    # read_symbol requires 'path' and 'name' for disambiguation
    resp = execute_read_symbol({"name": "hello", "path": f"{root_id}/main.py"}, db, tool_context["logger"], roots)
    assert "s:name=hello" in resp["content"][0]["text"]
    assert "def%20hello" in resp["content"][0]["text"]

def test_status_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    indexer = MagicMock()
    indexer.status.index_ready = True
    indexer.status.scanned_files = 2
    cfg = MagicMock()
    cfg.include_ext = [".py", ".js"]
    resp = execute_status({"details": True}, indexer, db, cfg, roots[0], "1.0.0", tool_context["logger"])
    assert "index_ready=true" in resp["content"][0]["text"]

def test_repo_candidates_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    resp = execute_repo_candidates({"query": "repo"}, db, tool_context["logger"], roots)
    assert "r:repo=repo1" in resp["content"][0]["text"]

def test_get_snippet_logic_integrity(tool_context):
    db, roots = tool_context["db"], tool_context["roots"]
    root_id = tool_context["root_id"]
    # get_snippet requires 'tag' or 'query'
    # We'll use query to search for existing content
    db.search_snippets = MagicMock(return_value=[{
        "id": 1, "tag": "test", "path": f"{root_id}/main.py", "start_line": 1, "end_line": 1, "content": "def hello():"
    }])
    args = {"query": "hello"}
    resp = execute_get_snippet(args, db, tool_context["logger"], roots)
    assert "PACK1 tool=get_snippet ok=true" in resp["content"][0]["text"]
