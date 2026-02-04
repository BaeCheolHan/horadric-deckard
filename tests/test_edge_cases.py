import json
import os
import time
import sqlite3
import threading
from pathlib import Path

import pytest

from sari.core.db import LocalSearchDB
from sari.mcp.tools import call_graph as call_graph_tool
from sari.mcp.tools import doctor as doctor_tool
from sari.mcp.tools import get_snippet as get_snippet_tool
from sari.core import workspace as workspace_mod


class SqliteDB:
    def __init__(self):
        self._read = sqlite3.connect(":memory:")
        self._read.row_factory = sqlite3.Row

    def get_read_connection(self):
        return self._read


def _init_call_graph_db():
    db = SqliteDB()
    cur = db._read.cursor()
    cur.execute(
        """
        CREATE TABLE symbols (
            path TEXT,
            name TEXT,
            kind TEXT,
            line INTEGER,
            end_line INTEGER,
            qualname TEXT,
            symbol_id TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE symbol_relations (
            from_path TEXT,
            from_symbol TEXT,
            from_symbol_id TEXT,
            to_path TEXT,
            to_symbol TEXT,
            to_symbol_id TEXT,
            rel_type TEXT,
            line INTEGER
        )
        """
    )
    cur.execute(
        "INSERT INTO symbols (path, name, kind, line, end_line, qualname, symbol_id) VALUES (?,?,?,?,?,?,?)",
        ("root/a.py", "process", "function", 1, 10, "process", "sid_t"),
    )
    cur.execute(
        "INSERT INTO symbol_relations VALUES (?,?,?,?,?,?,?,?)",
        ("root/a.py", "process", "sid_t", "root/app/x.py", "A", "sid_a", "calls", 5),
    )
    cur.execute(
        "INSERT INTO symbol_relations VALUES (?,?,?,?,?,?,?,?)",
        ("root/a.py", "process", "sid_t", "root/tests/y.py", "B", "sid_b", "calls", 6),
    )
    db._read.commit()
    return db


def test_call_graph_filters_and_summary():
    db = _init_call_graph_db()
    payload = call_graph_tool.build_call_graph(
        {"symbol": "process", "depth": 2, "include_path": ["root/"], "exclude_path": ["tests"], "sort": "name"},
        db,
        [],
    )
    assert payload["summary"]["downstream_nodes"] == 1
    assert "SUMMARY:" in payload["tree"]


def test_snippet_remap_update_and_snapshots(tmp_path, monkeypatch):
    db_path = tmp_path / "index.db"
    db = LocalSearchDB(str(db_path))

    # Insert file content
    file_path = "root-aaaa/foo.py"
    original = "a\nb\nc\nd\n"
    updated = "a\nx\nb\nc\nd\n"
    now = int(time.time())
    db.register_writer_thread(threading.get_ident())
    db.upsert_files([(file_path, "__root__", now, len(original), original, now)])

    # Insert snippet row (lines 2-3 -> b,c)
    snippet_content = "b\nc"
    snippet_hash = "dummy"
    anchor_before = "a"
    anchor_after = "d"
    db.upsert_snippet_tx(
        db._write.cursor(),
        [
            (
                "tag1",
                file_path,
                2,
                3,
                snippet_content,
                snippet_hash,
                anchor_before,
                anchor_after,
                "__root__",
                "root-aaaa",
                "",
                "",
                now,
                now,
            )
        ],
    )
    db._write.commit()

    # Update file content in DB
    db.upsert_files([(file_path, "__root__", now + 1, len(updated), updated, now + 1)])

    diff_path = tmp_path / "snippet.diff"
    payload = get_snippet_tool.build_get_snippet(
        {"tag": "tag1", "remap": True, "update": True, "diff_path": str(diff_path)},
        db,
        [],
    )
    res = payload["results"][0]
    assert res.get("updated") is True
    # Verify snippet location updated
    row = db.get_snippet_by_key("tag1", file_path, 2, 3)
    assert row is None
    # New location should be 3-4 (1-based): a,x,b,c,d
    row2 = db.list_snippets_by_tag("tag1")[0]
    assert row2["start_line"] == 3
    assert row2["end_line"] == 4
    # Snapshot files should exist in diff directory
    snapshot_files = list((tmp_path).glob("tag1_*_stored.txt")) + list((tmp_path).glob("tag1_*_current.txt"))
    assert snapshot_files

    db.close()


def test_doctor_auto_fix_rescan(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    db_path = tmp_path / "index.db"
    config_path.write_text(
        json.dumps({"db_path": str(db_path), "workspace_roots": [str(tmp_path)]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SARI_CONFIG", str(config_path))
    monkeypatch.setenv("SARI_FORMAT", "json")

    # Ensure DB exists
    db = LocalSearchDB(str(db_path))
    db.close()

    monkeypatch.setattr(workspace_mod.WorkspaceManager, "resolve_workspace_root", staticmethod(lambda root_uri=None: str(tmp_path)))

    res = doctor_tool.execute_doctor({"auto_fix": True, "auto_fix_rescan": True, "include_db": True, "include_network": False, "include_port": False, "include_disk": False})
    text = res["content"][0]["text"]
    payload = json.loads(text)
    names = [r["name"] for r in payload.get("results", [])]
    assert "Auto Fix Rescan Start" in names
    assert "Auto Fix Rescan" in names
    monkeypatch.delenv("SARI_CONFIG", raising=False)
    monkeypatch.delenv("SARI_FORMAT", raising=False)


def test_doctor_auto_fix_rescan_skipped(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    db_path = tmp_path / "index.db"
    config_path.write_text(
        json.dumps({"db_path": str(db_path), "workspace_roots": [str(tmp_path)]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SARI_CONFIG", str(config_path))
    monkeypatch.setenv("SARI_FORMAT", "json")
    db = LocalSearchDB(str(db_path))
    db.close()

    monkeypatch.setattr(workspace_mod.WorkspaceManager, "resolve_workspace_root", staticmethod(lambda root_uri=None: str(tmp_path)))
    monkeypatch.setattr(doctor_tool, "_run_auto_fixes", lambda ws_root, actions: [{"name": "Auto Fix DB Migrate", "passed": False, "error": "fail"}])

    res = doctor_tool.execute_doctor({"auto_fix": True, "auto_fix_rescan": True, "include_db": True, "include_network": False, "include_port": False, "include_disk": False})
    text = res["content"][0]["text"]
    payload = json.loads(text)
    names = [r["name"] for r in payload.get("results", [])]
    assert "Auto Fix Rescan Skipped" in names
    monkeypatch.delenv("SARI_CONFIG", raising=False)
    monkeypatch.delenv("SARI_FORMAT", raising=False)


def test_snippet_update_skipped_on_invalid_remap(tmp_path):
    db_path = tmp_path / "index.db"
    db = LocalSearchDB(str(db_path))
    file_path = "root-aaaa/foo.py"
    content = "a\nb\nc\n"
    now = int(time.time())
    db.register_writer_thread(threading.get_ident())
    db.upsert_files([(file_path, "__root__", now, len(content), content, now)])

    db.upsert_snippet_tx(
        db._write.cursor(),
        [("tag2", file_path, 2, 3, "b\nc", "dummy", "a", "c", "__root__", "root-aaaa", "", "", now, now)],
    )
    db._write.commit()

    payload = get_snippet_tool.build_get_snippet({"tag": "tag2", "remap": False, "update": True}, db, [])
    res = payload["results"][0]
    assert res.get("updated") is False
    assert res.get("update_skipped_reason") == "not_remapped"
    db.close()
