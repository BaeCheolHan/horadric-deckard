import os

from mcp.tools.list_files import execute_list_files


class DummyDB:
    def list_files(self, **kwargs):
        files = [{"path": "root-aaaa/a.txt"}, {"path": "root-aaaa/b.txt"}]
        meta = {"total": 2}
        return files, meta

    def get_repo_stats(self, root_ids=None):
        return {"repo": 2}


class DummyLogger:
    def log_telemetry(self, _msg):
        pass


def test_list_files_pack(tmp_path):
    res = execute_list_files({}, DummyDB(), DummyLogger(), [str(tmp_path)])
    text = res["content"][0]["text"]
    assert text.startswith("PACK1 tool=list_files ok=true")
    assert "p:" in text


def test_list_files_json_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = execute_list_files({}, DummyDB(), DummyLogger(), [str(tmp_path)])
    assert res.get("meta", {}).get("mode") == "summary"
    monkeypatch.delenv("DECKARD_FORMAT", raising=False)


def test_list_files_json_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKARD_FORMAT", "json")
    res = execute_list_files({"repo": "repo"}, DummyDB(), DummyLogger(), [str(tmp_path)])
    assert res.get("files")
    monkeypatch.delenv("DECKARD_FORMAT", raising=False)
