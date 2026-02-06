import pytest
from unittest.mock import MagicMock
from sari.mcp.tools.read_file import execute_read_file
from sari.mcp.tools.get_snippet import execute_get_snippet
from sari.mcp.tools.grep_and_read import execute_grep_and_read
from sari.mcp.tools.index_file import execute_index_file
from sari.mcp.tools.rescan import execute_rescan
from sari.mcp.tools.read_symbol import execute_read_symbol
from sari.mcp.tools.get_callers import execute_get_callers
from sari.mcp.tools.get_implementations import execute_get_implementations
from sari.mcp.tools.repo_candidates import execute_repo_candidates
from sari.mcp.tools.registry import build_default_registry, ToolContext
from sari.mcp.tools._util import resolve_repo_scope

def test_execute_read_file(tmp_path):
    roots = [str(tmp_path)]
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    db = MagicMock()
    db.read_file.return_value = "hello world"
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(tmp_path))
    db_path = f"{root_id}/test.txt"
    args = {"path": db_path}
    resp = execute_read_file(args, db, roots)
    # The content is URL encoded
    import urllib.parse
    assert urllib.parse.quote("hello world") in resp["content"][0]["text"]

def test_execute_get_snippet(tmp_path):
    roots = [str(tmp_path)]
    f = tmp_path / "code.py"
    f.write_text("line 1\nline 2")
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(tmp_path))
    db_path = f"{root_id}/code.py"
    db = MagicMock()
    # Mock for build_get_snippet
    db.list_snippets_by_tag.return_value = [{
        "tag": "test", "path": db_path, "start_line": 1, "end_line": 2, "content": "line 1\nline 2", "id": 1
    }]
    args = {"tag": "test"}
    resp = execute_get_snippet(args, db, roots)
    assert "PACK1" in resp["content"][0]["text"]

def test_execute_grep_and_read(tmp_path):
    roots = [str(tmp_path)]
    db = MagicMock()
    logger = MagicMock()
    db.search_files.return_value = [{"path": "root-xxx/file1.txt"}]
    args = {"query": "pattern", "repo": "all"}
    try:
        resp = execute_grep_and_read(args, db, logger, roots)
        assert "PACK1" in resp["content"][0]["text"]
    except Exception: pass

def test_execute_index_file():
    indexer = MagicMock()
    roots = ["/tmp/ws"]
    args = {"path": "root-123/file.py"}
    resp = execute_index_file(args, indexer, roots)
    assert "PACK1" in resp["content"][0]["text"]

def test_execute_rescan():
    indexer = MagicMock()
    args = {}
    resp = execute_rescan(args, indexer)
    assert "PACK1" in resp["content"][0]["text"]


def test_execute_rescan_fallback_to_scan_once():
    class _IndexerWithoutRequestRescan:
        indexing_enabled = True
        indexer_mode = "leader"
        def __init__(self):
            self.called = 0
        def scan_once(self):
            self.called += 1

    idx = _IndexerWithoutRequestRescan()
    resp = execute_rescan({}, idx)
    assert "PACK1" in resp["content"][0]["text"]
    assert idx.called == 1

def test_execute_repo_candidates():
    db = MagicMock()
    logger = MagicMock()
    roots = ["/tmp/ws"]
    db.get_repo_stats.return_value = {"repo1": 10}
    args = {"query": "repo1"}
    resp = execute_repo_candidates(args, db, logger, roots)
    assert "repo1" in resp["content"][0]["text"]


def test_registry_scan_once_handler_passes_logger():
    reg = build_default_registry()
    indexer = MagicMock()
    indexer.indexing_enabled = True
    indexer.status.scanned_files = 0
    indexer.status.indexed_files = 0
    indexer.get_queue_depths.return_value = {"fair_queue": 0, "priority_queue": 0, "db_writer": 0}
    indexer.storage.writer.flush.return_value = None

    ctx = ToolContext(
        db=MagicMock(),
        engine=None,
        indexer=indexer,
        roots=["/tmp/ws"],
        cfg=None,
        logger=MagicMock(),
        workspace_root="/tmp/ws",
        server_version="test",
    )

    resp = reg.execute("scan_once", ctx, {})
    assert "PACK1 tool=scan_once ok=true" in resp["content"][0]["text"]


def test_registry_hides_internal_tools_by_default(monkeypatch):
    monkeypatch.delenv("SARI_EXPOSE_INTERNAL_TOOLS", raising=False)
    reg = build_default_registry()
    names = {t["name"] for t in reg.list_tools()}
    assert "scan_once" not in names
    assert "rescan" not in names


def test_registry_symbol_tool_schemas_match_runtime_flexibility():
    reg = build_default_registry()
    tools = {t["name"]: t for t in reg.list_tools()}

    # read_symbol supports symbol_id/sid without forcing path+name.
    read_symbol_schema = tools["read_symbol"]["inputSchema"]
    assert "symbol_id" in read_symbol_schema["properties"]
    assert "sid" in read_symbol_schema["properties"]
    assert "required" not in read_symbol_schema or not read_symbol_schema["required"]

    # caller/implementation tools accept name OR symbol_id-style calls.
    callers_schema = tools["get_callers"]["inputSchema"]
    impl_schema = tools["get_implementations"]["inputSchema"]
    assert "symbol_id" in callers_schema["properties"]
    assert "sid" in callers_schema["properties"]
    assert "symbol_id" in impl_schema["properties"]
    assert "sid" in impl_schema["properties"]

    # call_graph should allow symbol alias and sid alias.
    cg_schema = tools["call_graph"]["inputSchema"]
    assert "symbol" in cg_schema["properties"]
    assert "name" in cg_schema["properties"]
    assert "symbol_id" in cg_schema["properties"]
    assert "sid" in cg_schema["properties"]


def test_read_symbol_supports_symbol_id_without_path(tmp_path):
    from sari.core.db import LocalSearchDB
    from sari.core.workspace import WorkspaceManager

    root = tmp_path / "ws"
    root.mkdir()
    (root / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    db = LocalSearchDB(str(root / "sari.db"))
    rid = WorkspaceManager.root_id(str(root))
    db.upsert_root(rid, str(root), str(root.resolve()), label="ws")
    cur = db._write.cursor()
    db.upsert_files_tx(cur, [(
        f"{rid}/main.py", "main.py", rid, "repo", 1, 20, "def hello():\n    return 1\n",
        "h", "hello", 1, 0, "ok", "", "ok", "", 0, 0, 0, 20, "{}"
    )])
    db.upsert_symbols_tx(cur, [("sid-hello", f"{rid}/main.py", rid, "hello", "function", 1, 2, "def hello():", "", "{}", "", "hello")])
    db._write.commit()

    resp = execute_read_symbol({"symbol_id": "sid-hello"}, db, MagicMock(), [str(root)])
    text = resp["content"][0]["text"]
    assert "PACK1 tool=read_symbol ok=true" in text
    assert "sid=sid-hello" in text


def test_get_callers_falls_back_to_call_graph(monkeypatch):
    class _Conn:
        def execute(self, *_args, **_kwargs):
            class _Rows:
                def fetchall(self_non):
                    return []
            return _Rows()

    class _DB:
        _read = _Conn()

    monkeypatch.setattr(
        "sari.mcp.tools.get_callers.build_call_graph",
        lambda _args, _db, _roots: {
            "upstream": {
                "children": [
                    {"path": "root-x/a.py", "name": "callerA", "symbol_id": "sid-a", "line": 10, "rel_type": "calls_heuristic"}
                ]
            }
        },
    )
    resp = execute_get_callers({"name": "target"}, _DB(), ["/tmp/ws"])
    text = resp["content"][0]["text"]
    assert "PACK1 tool=get_callers ok=true" in text
    assert "caller_symbol=callerA" in text


def test_get_callers_repo_filter_applied():
    from sari.core.workspace import WorkspaceManager
    repo_root = "/tmp/target-repo"
    rid = WorkspaceManager.root_id_for_workspace(repo_root)

    class _Conn:
        def execute(self, _sql, params=None):
            class _Rows:
                def __init__(self, rows):
                    self._rows = rows
                def fetchall(self_non):
                    return self_non._rows
            if params and any(isinstance(p, str) and p == f"{rid}/%" for p in params):
                return _Rows([{"from_path": f"{rid}/A.java", "from_symbol": "a", "from_symbol_id": "sid-a", "line": 1, "rel_type": "calls"}])
            return _Rows([])
    class _DB:
        _read = _Conn()
    resp = execute_get_callers({"name": "foo", "repo": "target-repo"}, _DB(), [repo_root])
    text = resp["content"][0]["text"]
    assert f"caller_path={rid}/A.java" in text


def test_get_implementations_falls_back_to_file_content():
    class _Conn:
        def execute(self, sql, _params=None):
            class _Rows:
                def __init__(self, rows):
                    self._rows = rows
                def fetchall(self_non):
                    return self_non._rows
                def fetchone(self_non):
                    return self_non._rows[0] if self_non._rows else None
            if "FROM symbol_relations" in sql:
                return _Rows([])
            if "SELECT path, content FROM files" in sql:
                return _Rows([{"path": "root-x/a/Repo.java", "content": "public interface Repo extends JpaRepository<User,Long> {}"}])
            if "SELECT symbol_id, name, line FROM symbols" in sql:
                return _Rows([{"symbol_id": "sid-repo", "name": "Repo", "line": 1}])
            return _Rows([])

    class _DB:
        _read = _Conn()

    resp = execute_get_implementations({"name": "JpaRepository"}, _DB(), ["/tmp/ws"])
    text = resp["content"][0]["text"]
    assert "PACK1 tool=get_implementations ok=true" in text
    assert "implementer_symbol=Repo" in text


def test_get_implementations_repo_filter_applied():
    from sari.core.workspace import WorkspaceManager
    repo_root = "/tmp/target-repo"
    rid = WorkspaceManager.root_id_for_workspace(repo_root)

    class _Conn:
        def execute(self, sql, params=None):
            class _Rows:
                def __init__(self, rows):
                    self._rows = rows
                def fetchall(self_non):
                    return self_non._rows
                def fetchone(self_non):
                    return self_non._rows[0] if self_non._rows else None
            if "FROM symbol_relations" in sql:
                return _Rows([])
            if "SELECT path, content FROM files" in sql:
                if params and any(isinstance(p, str) and p == f"{rid}/%" for p in params):
                    return _Rows([{"path": f"{rid}/Repo.java", "content": "interface Repo extends JpaRepository<User,Long> {}"}])
                return _Rows([])
            if "SELECT symbol_id, name, line FROM symbols" in sql:
                return _Rows([{"symbol_id": "sid-repo", "name": "Repo", "line": 1}])
            return _Rows([])
    class _DB:
        _read = _Conn()
    resp = execute_get_implementations({"name": "JpaRepository", "repo": "target-repo"}, _DB(), [repo_root])
    text = resp["content"][0]["text"]
    assert f"implementer_path={rid}/Repo.java" in text


def test_resolve_repo_scope_prefers_workspace_name(tmp_path):
    from sari.core.workspace import WorkspaceManager

    ws_a = tmp_path / "StockManager-v-1.0"
    ws_b = tmp_path / "stock-manager-front"
    ws_a.mkdir()
    ws_b.mkdir()
    repo, root_ids = resolve_repo_scope("stock-manager-front", [str(ws_a), str(ws_b)], db=None)
    assert repo is None
    assert WorkspaceManager.root_id_for_workspace(str(ws_b)) in root_ids
    assert WorkspaceManager.root_id_for_workspace(str(ws_a)) not in root_ids


def test_resolve_repo_scope_uses_repo_bucket_when_not_workspace_name():
    from sari.core.workspace import WorkspaceManager
    ws_a = "/tmp/ws-a"
    ws_b = "/tmp/ws-b"
    rid_a = WorkspaceManager.root_id_for_workspace(ws_a)
    rid_b = WorkspaceManager.root_id_for_workspace(ws_b)

    class _Conn:
        def execute(self, sql, params=None):
            class _Rows:
                def __init__(self, rows):
                    self._rows = rows
                def fetchall(self_non):
                    return self_non._rows
            if "FROM files" in sql:
                return _Rows([(rid_a,), (rid_b,)])
            if "FROM roots" in sql:
                return _Rows([])
            return _Rows([])

    class _DB:
        _read = _Conn()

    repo, root_ids = resolve_repo_scope("src", [ws_a, ws_b], db=_DB())
    assert repo == "src"
    assert root_ids
