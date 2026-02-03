import io
import json
import os
import types
import sys
import importlib

import pytest

import mcp.proxy as proxy_mod


class DummyTelemetry:
    def __init__(self, fail=False):
        self.fail = fail
        self.lines = []
    def log_info(self, msg):
        if self.fail:
            raise RuntimeError("boom")
        self.lines.append(msg)
    def log_error(self, msg):
        if self.fail:
            raise RuntimeError("boom")
        self.lines.append(msg)


def test_log_helpers(monkeypatch):
    monkeypatch.setattr(proxy_mod, "telemetry", DummyTelemetry(fail=True))
    proxy_mod._log_info("x")
    proxy_mod._log_error("y")

def test_sys_path_insertion(monkeypatch):
    repo_root = str(proxy_mod.REPO_ROOT)
    if repo_root in sys.path:
        sys.path.remove(repo_root)
    importlib.reload(proxy_mod)
    assert repo_root in sys.path


def test_read_mcp_message_jsonl_and_framed():
    data = io.BytesIO(b'{"jsonrpc":"2.0"}\n')
    msg, mode = proxy_mod._read_mcp_message(data)
    assert mode == "jsonl"
    assert b"jsonrpc" in msg

    body = b'{"jsonrpc":"2.0"}'
    data = io.BytesIO(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
    msg, mode = proxy_mod._read_mcp_message(data)
    assert mode == "framed"
    assert msg == body


def test_read_mcp_message_invalid_header():
    data = io.BytesIO(b"Bad: 1\r\n\r\n")
    assert proxy_mod._read_mcp_message(data) is None

    data = io.BytesIO(b"Content-Length: nope\r\n\r\n")
    assert proxy_mod._read_mcp_message(data) is None

    data = io.BytesIO(b"\r\n\r\n")
    assert proxy_mod._read_mcp_message(data) is None

    data = io.BytesIO(b"X\r\n\r\n")
    assert proxy_mod._read_mcp_message(data) is None

    data = io.BytesIO(b"X\r\nContent-Length: 1\r\n\r\nx")
    msg, mode = proxy_mod._read_mcp_message(data)
    assert mode == "framed"
    assert msg == b"x"

    data = io.BytesIO(b"Content-Length: 1\r\n\r\n")
    assert proxy_mod._read_mcp_message(data) is None


def test_start_daemon_if_needed_success(monkeypatch, tmp_path):
    calls = {"n": 0}
    def fake_conn(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionRefusedError()
        class DummySock:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        return DummySock()

    monkeypatch.setattr(proxy_mod.socket, "create_connection", fake_conn)
    monkeypatch.setattr(proxy_mod, "_lock_file", lambda *_: None)
    monkeypatch.setattr(proxy_mod, "_unlock_file", lambda *_: None)
    monkeypatch.setattr(proxy_mod.subprocess, "Popen", lambda *args, **kwargs: None)
    monkeypatch.setattr(proxy_mod.time, "sleep", lambda *_: None)
    assert proxy_mod.start_daemon_if_needed("127.0.0.1", 1) is True


def test_start_daemon_if_needed_failure(monkeypatch):
    monkeypatch.setattr(proxy_mod.socket, "create_connection", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionRefusedError()))
    monkeypatch.setattr(proxy_mod, "_lock_file", lambda *_: None)
    monkeypatch.setattr(proxy_mod, "_unlock_file", lambda *_: None)
    monkeypatch.setattr(proxy_mod.subprocess, "Popen", lambda *args, **kwargs: None)
    monkeypatch.setattr(proxy_mod.time, "sleep", lambda *_: None)
    assert proxy_mod.start_daemon_if_needed("127.0.0.1", 1) is False


def test_start_daemon_if_needed_already_running(monkeypatch):
    class DummySock:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(proxy_mod.socket, "create_connection", lambda *args, **kwargs: DummySock())
    assert proxy_mod.start_daemon_if_needed("127.0.0.1", 1) is True


def test_start_daemon_detect_workspace_root(monkeypatch, tmp_path):
    calls = {"n": 0}
    def fake_conn(*_args, **_kwargs):
        calls["n"] += 1
        raise ConnectionRefusedError()
    monkeypatch.setattr(proxy_mod.socket, "create_connection", fake_conn)
    monkeypatch.setattr(proxy_mod, "_lock_file", lambda *_: None)
    monkeypatch.setattr(proxy_mod, "_unlock_file", lambda *_: None)
    monkeypatch.setattr(proxy_mod.subprocess, "Popen", lambda *args, **kwargs: None)
    monkeypatch.setattr(proxy_mod.time, "sleep", lambda *_: None)

    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    monkeypatch.setattr(proxy_mod.Path, "cwd", lambda: child)
    monkeypatch.delenv("DECKARD_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_WORKSPACE_ROOT", raising=False)
    proxy_mod.start_daemon_if_needed("127.0.0.1", 1)


def test_forward_stdin_to_socket_injects_root(monkeypatch):
    class DummySock:
        def __init__(self):
            self.sent = []
        def sendall(self, data):
            self.sent.append(data)
        def close(self):
            return None

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
    payload = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    buf = io.BytesIO(payload)
    monkeypatch.setattr(proxy_mod.sys, "stdin", types.SimpleNamespace(buffer=buf))
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", "/tmp/ws")

    sock = DummySock()
    mode_holder = {"mode": None}
    proxy_mod.forward_stdin_to_socket(sock, mode_holder)
    assert mode_holder["mode"] in ("framed", "jsonl")
    sent = b"".join(sock.sent)
    assert b"rootUri" in sent


def test_forward_socket_to_stdout(monkeypatch):
    body = b'{"jsonrpc":"2.0"}'
    framed = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    fileobj = io.BytesIO(framed)

    class DummySock:
        def makefile(self, _mode):
            return fileobj

    out = io.BytesIO()
    monkeypatch.setattr(proxy_mod.sys, "stdout", types.SimpleNamespace(buffer=out))
    monkeypatch.setattr(proxy_mod.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    mode_holder = {"mode": "framed"}
    with pytest.raises(SystemExit):
        proxy_mod.forward_socket_to_stdout(DummySock(), mode_holder)
    assert b"Content-Length" in out.getvalue()


def test_forward_socket_to_stdout_zero_length(monkeypatch):
    framed = b"Content-Length: 0\r\n\r\n"
    fileobj = io.BytesIO(framed)

    class DummySock:
        def makefile(self, _mode):
            return fileobj

    out = io.BytesIO()
    monkeypatch.setattr(proxy_mod.sys, "stdout", types.SimpleNamespace(buffer=out))
    monkeypatch.setattr(proxy_mod.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    with pytest.raises(SystemExit):
        proxy_mod.forward_socket_to_stdout(DummySock(), {"mode": "framed"})


def test_forward_socket_to_stdout_jsonl(monkeypatch):
    body = b'{"jsonrpc":"2.0"}'
    framed = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    fileobj = io.BytesIO(framed)

    class DummySock:
        def makefile(self, _mode):
            return fileobj

    out = io.BytesIO()
    monkeypatch.setattr(proxy_mod.sys, "stdout", types.SimpleNamespace(buffer=out))
    monkeypatch.setattr(proxy_mod.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    mode_holder = {"mode": "jsonl"}
    with pytest.raises(SystemExit):
        proxy_mod.forward_socket_to_stdout(DummySock(), mode_holder)
    assert b"\n" in out.getvalue()


def test_forward_socket_to_stdout_error(monkeypatch):
    class DummySock:
        def makefile(self, _mode):
            raise RuntimeError("boom")
    monkeypatch.setattr(proxy_mod.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    with pytest.raises(SystemExit):
        proxy_mod.forward_socket_to_stdout(DummySock(), {"mode": "framed"})


def test_forward_socket_to_stdout_empty_body(monkeypatch):
    framed = b"Content-Length: 2\r\n\r\n"
    fileobj = io.BytesIO(framed)

    class DummySock:
        def makefile(self, _mode):
            return fileobj

    monkeypatch.setattr(proxy_mod.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    with pytest.raises(SystemExit):
        proxy_mod.forward_socket_to_stdout(DummySock(), {"mode": "framed"})


def test_forward_stdin_to_socket_list_and_errors(monkeypatch):
    class DummySock:
        def __init__(self):
            self.sent = []
        def sendall(self, data):
            self.sent.append(data)
        def close(self):
            return None

    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    body = json.dumps(batch).encode("utf-8")
    payload = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    buf = io.BytesIO(payload)
    monkeypatch.setattr(proxy_mod.sys, "stdin", types.SimpleNamespace(buffer=buf))
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", "/tmp/ws")

    sock = DummySock()
    mode_holder = {"mode": None}
    proxy_mod.forward_stdin_to_socket(sock, mode_holder)
    assert b"rootUri" in b"".join(sock.sent)

    buf = io.BytesIO(b"Content-Length: 4\r\n\r\nxxxx")
    monkeypatch.setattr(proxy_mod.sys, "stdin", types.SimpleNamespace(buffer=buf))
    class BadSock(DummySock):
        def sendall(self, _data):
            raise RuntimeError("send")
    with pytest.raises(SystemExit):
        monkeypatch.setattr(proxy_mod.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))
        proxy_mod.forward_stdin_to_socket(BadSock(), {"mode": None})


def test_forward_stdin_to_socket_no_inject(monkeypatch):
    class DummySock:
        def __init__(self):
            self.sent = []
        def sendall(self, data):
            self.sent.append(data)
        def close(self):
            return None

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"rootUri": "file:///tmp"}}).encode("utf-8")
    payload = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    buf = io.BytesIO(payload)
    monkeypatch.setattr(proxy_mod.sys, "stdin", types.SimpleNamespace(buffer=buf))
    monkeypatch.delenv("DECKARD_WORKSPACE_ROOT", raising=False)
    sock = DummySock()
    proxy_mod.forward_stdin_to_socket(sock, {"mode": None})
    sent = b"".join(sock.sent)
    assert b"rootUri" in sent


def test_forward_stdin_to_socket_missing_ws(monkeypatch):
    class DummySock:
        def __init__(self):
            self.sent = []
        def sendall(self, data):
            self.sent.append(data)
        def close(self):
            return None

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
    payload = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    buf = io.BytesIO(payload)
    monkeypatch.setattr(proxy_mod.sys, "stdin", types.SimpleNamespace(buffer=buf))
    monkeypatch.delenv("DECKARD_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_WORKSPACE_ROOT", raising=False)
    sock = DummySock()
    proxy_mod.forward_stdin_to_socket(sock, {"mode": None})


def test_main_paths(monkeypatch):
    monkeypatch.setattr(proxy_mod.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))
    monkeypatch.setattr(proxy_mod, "start_daemon_if_needed", lambda *_: False)
    with pytest.raises(SystemExit):
        proxy_mod.main()

    class DummySock:
        pass

    monkeypatch.setattr(proxy_mod, "start_daemon_if_needed", lambda *_: True)
    monkeypatch.setattr(proxy_mod.socket, "create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(SystemExit):
        proxy_mod.main()

    monkeypatch.setattr(proxy_mod.socket, "create_connection", lambda *_args, **_kwargs: DummySock())
    monkeypatch.setattr(proxy_mod.threading, "Thread", lambda *args, **kwargs: types.SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(proxy_mod, "forward_stdin_to_socket", lambda *_: None)
    proxy_mod.main()
