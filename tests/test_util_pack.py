import os
from pathlib import Path

from mcp.tools._util import (
    pack_header,
    pack_line,
    pack_error,
    pack_truncated,
    pack_encode_id,
    pack_encode_text,
    ErrorCode,
    resolve_db_path,
    resolve_root_ids,
    mcp_response,
)


def test_pack_header_line_error():
    header = pack_header("search", {"q": "abc"}, returned=2, total=3, total_mode="exact")
    assert header.startswith("PACK1 tool=search ok=true")
    line = pack_line("m", {"total": "3"})
    assert line.startswith("m:")
    err = pack_error("search", ErrorCode.INVALID_ARGS, "missing")
    assert "ok=false" in err
    assert "code=INVALID_ARGS" in err


def test_resolve_db_path(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "a.txt"
    file_path.write_text("hi", encoding="utf-8")

    db_path = resolve_db_path(str(file_path), [str(root)])
    assert db_path.startswith("root-")
    assert db_path.endswith("/a.txt")

    # Out of scope
    other = tmp_path / "other.txt"
    other.write_text("x", encoding="utf-8")
    assert resolve_db_path(str(other), [str(root)]) is None


def test_resolve_root_ids(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    root_ids = resolve_root_ids([str(root)])
    assert root_ids and root_ids[0].startswith("root-")


def test_mcp_response_json_mode(monkeypatch):
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = mcp_response("x", lambda: "PACK1", lambda: {"ok": True})
    assert res.get("ok") is True
    monkeypatch.delenv("DECKARD_FORMAT", raising=False)


def test_mcp_response_error_pack(monkeypatch):
    monkeypatch.setenv("DECKARD_FORMAT", "pack")
    def _bad():
        raise RuntimeError("boom")
    res = mcp_response("x", _bad, lambda: {"ok": True})
    text = res["content"][0]["text"]
    assert "ok=false" in text
    monkeypatch.delenv("DECKARD_FORMAT", raising=False)


def test_resolve_root_ids_empty(monkeypatch):
    import mcp.tools._util as util
    monkeypatch.setattr(util, "WorkspaceManager", None)
    assert util.resolve_root_ids([]) == []


def test_resolve_db_path_root_id(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    rid = resolve_root_ids([str(root)])[0]
    assert resolve_db_path(rid + "/file.txt", [str(root)]) == rid + "/file.txt"


def test_pack_truncated():
    line = pack_truncated(10, 5, "maybe")
    assert "truncated=maybe" in line


def test_pack_encode_helpers():
    assert pack_encode_id("a b") == "a%20b"
    assert pack_encode_text("a b") == "a%20b"
