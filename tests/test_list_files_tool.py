import os

from sari.mcp.tools.list_files import execute_list_files


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
    assert "p:" not in text
    assert "r:" in text
    assert len(text.encode("utf-8")) < 2048


def test_list_files_json_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("SARI_FORMAT", "json")
    res = execute_list_files({}, DummyDB(), DummyLogger(), [str(tmp_path)])
    assert res.get("meta", {}).get("mode") == "summary"
    payload = res["content"][0]["text"]
    assert len(payload.encode("utf-8")) < 2048
    monkeypatch.delenv("SARI_FORMAT", raising=False)


def test_list_files_json_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("SARI_FORMAT", "json")
    res = execute_list_files({"repo": "repo"}, DummyDB(), DummyLogger(), [str(tmp_path)])
    assert res.get("files")
    monkeypatch.delenv("SARI_FORMAT", raising=False)
