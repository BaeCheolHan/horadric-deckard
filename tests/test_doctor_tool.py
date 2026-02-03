import socket
import shutil

from mcp.tools import doctor as doctor_tool
from app.db import LocalSearchDB


def test_check_port_ok():
    res = doctor_tool._check_port(0, "Test")
    assert res["passed"] is True


def test_check_port_in_use():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    res = doctor_tool._check_port(port, "Test")
    sock.close()
    assert res["passed"] is False


def test_execute_doctor_minimal(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor_tool.WorkspaceManager, "resolve_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(doctor_tool, "get_daemon_address", lambda: ("127.0.0.1", 12345))
    monkeypatch.setattr(doctor_tool, "is_daemon_running", lambda host, port: False)
    monkeypatch.setattr(doctor_tool, "read_pid", lambda: 0)

    res = doctor_tool.execute_doctor({
        "include_network": False,
        "include_port": False,
        "include_db": False,
        "include_disk": False,
        "include_daemon": True,
        "include_venv": True,
        "search_usage": {"read_without_search": 1, "search": 0, "search_symbols": 0},
        "search_first_mode": "warn",
    })
    text = res["content"][0]["text"]
    assert "PACK1 tool=doctor ok=true" in text


def test_check_daemon_running(monkeypatch):
    monkeypatch.setattr(doctor_tool, "get_daemon_address", lambda: ("127.0.0.1", 12345))
    monkeypatch.setattr(doctor_tool, "is_daemon_running", lambda host, port: True)
    monkeypatch.setattr(doctor_tool, "read_pid", lambda: 42)
    res = doctor_tool._check_daemon()
    assert res["passed"] is True


def test_search_first_usage_ok():
    res = doctor_tool._check_search_first_usage({"read_without_search": 0, "search": 1, "search_symbols": 0}, "warn")
    assert res["passed"] is True


def test_check_disk_and_network(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: (100, 90, 10))
    res = doctor_tool._check_disk_space(str(tmp_path), min_gb=1.0)
    assert res["passed"] is False

    def _fail(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(socket, "create_connection", _fail)
    res = doctor_tool._check_network()
    assert res["passed"] is False


def test_check_db_ok(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "index.db"
    cfg_path.write_text("{\"db_path\": \"" + str(db_path) + "\"}", encoding="utf-8")
    monkeypatch.setenv("DECKARD_CONFIG", str(cfg_path))
    LocalSearchDB(str(db_path)).close()
    results = doctor_tool._check_db(str(tmp_path))
    assert any(r["name"].startswith("DB") for r in results)


def test_check_db_missing(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "missing.db"
    cfg_path.write_text("{\"db_path\": \"" + str(db_path) + "\"}", encoding="utf-8")
    monkeypatch.setenv("DECKARD_CONFIG", str(cfg_path))
    results = doctor_tool._check_db(str(tmp_path))
    assert any(r["name"] == "DB Existence" and r["passed"] is False for r in results)


def test_execute_doctor_ports(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor_tool.WorkspaceManager, "resolve_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(doctor_tool, "get_daemon_address", lambda: ("127.0.0.1", 0))
    monkeypatch.setattr(doctor_tool, "is_daemon_running", lambda host, port: False)
    monkeypatch.setattr(doctor_tool, "read_pid", lambda: 0)
    monkeypatch.setattr(doctor_tool.ServerRegistry, "get_instance", lambda self, _ws: {"port": 0})
    res = doctor_tool.execute_doctor({
        "include_network": False,
        "include_port": True,
        "include_db": False,
        "include_disk": False,
        "include_daemon": False,
        "include_venv": False,
        "port": 0,
    })
    text = res["content"][0]["text"]
    assert "PACK1 tool=doctor ok=true" in text
