from pathlib import Path

from mcp.tools.read_file import execute_read_file
from mcp.tools.read_symbol import execute_read_symbol


class DummyDB:
    def has_legacy_paths(self):
        return False

    def read_file(self, _db_path):
        return "file content"

    def get_symbol_block(self, _db_path, _name):
        return {
            "name": "fn",
            "start_line": 1,
            "end_line": 2,
            "content": "def fn():\n  return 1",
            "docstring": "doc",
            "metadata": "{}",
        }


class DummyDBNoSymbol(DummyDB):
    def get_symbol_block(self, _db_path, _name):
        return None


class DummyLogger:
    def log_telemetry(self, _msg):
        pass


def test_read_file_out_of_scope(tmp_path):
    db = DummyDB()
    res = execute_read_file({"path": str(tmp_path / "x.txt")}, db, [str(tmp_path / "other")])
    text = res["content"][0]["text"]
    assert "ERR_ROOT_OUT_OF_SCOPE" in text


def test_read_file_success(tmp_path):
    db = DummyDB()
    file_path = tmp_path / "x.txt"
    file_path.write_text("hi", encoding="utf-8")
    res = execute_read_file({"path": str(file_path)}, db, [str(tmp_path)])
    text = res["content"][0]["text"]
    assert "PACK1 tool=read_file" in text


def test_read_symbol_success(tmp_path):
    db = DummyDB()
    file_path = tmp_path / "x.txt"
    file_path.write_text("hi", encoding="utf-8")
    res = execute_read_symbol({"path": str(file_path), "name": "fn"}, db, DummyLogger(), [str(tmp_path)])
    text = res["content"][0]["text"]
    assert "PACK1 tool=read_symbol" in text


def test_read_symbol_not_found(tmp_path):
    db = DummyDBNoSymbol()
    file_path = tmp_path / "x.txt"
    file_path.write_text("hi", encoding="utf-8")
    res = execute_read_symbol({"path": str(file_path), "name": "fn"}, db, DummyLogger(), [str(tmp_path)])
    text = res["content"][0]["text"]
    assert "NOT_INDEXED" in text
