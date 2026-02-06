import pytest
import json
import threading
import time
import io
from unittest.mock import MagicMock, patch
from sari.mcp.server import LocalSearchMCPServer
import sari.mcp.server as server_mod

def test_server_handle_initialize():
    server = LocalSearchMCPServer("/tmp/ws")
    params = {"rootUri": "file:///tmp/ws2"}
    resp = server.handle_initialize(params)
    assert resp["protocolVersion"] == "2025-11-25"
    assert "tools" in resp["capabilities"]
    assert "prompts" in resp["capabilities"]
    assert "resources" in resp["capabilities"]
    from sari.core.workspace import WorkspaceManager
    expected = WorkspaceManager.normalize_path("/tmp/ws2")
    assert server.workspace_root == expected

def test_server_handle_request_ping():
    server = LocalSearchMCPServer("/tmp/ws")
    req = {"id": 1, "method": "ping", "params": {}}
    resp = server.handle_request(req)
    assert resp["id"] == 1
    assert "result" in resp

def test_server_handle_request_not_found():
    server = LocalSearchMCPServer("/tmp/ws")
    req = {"id": 1, "method": "non_existent", "params": {}}
    resp = server.handle_request(req)
    assert resp["error"]["code"] == -32601

def test_server_handle_request_prompts_and_resources_list():
    server = LocalSearchMCPServer("/tmp/ws")
    prompts_resp = server.handle_request({"id": 1, "method": "prompts/list", "params": {}})
    resources_resp = server.handle_request({"id": 2, "method": "resources/list", "params": {}})
    templates_resp = server.handle_request({"id": 3, "method": "resources/templates/list", "params": {}})
    assert prompts_resp["result"] == {"prompts": []}
    assert resources_resp["result"] == {"resources": []}
    assert templates_resp["result"] == {"resourceTemplates": []}

def test_server_worker_loop():
    # Test if worker loop processes a request from queue
    server = LocalSearchMCPServer("/tmp/ws")
    # Mock handle_request to verify it's called
    server.handle_request = MagicMock(return_value={"id": 1, "result": {}})
    # Mock stdout to avoid printing to real stdout
    server._original_stdout = MagicMock()
    
    server._req_queue.put({"id": 1, "method": "ping"})
    
    import time
    time.sleep(0.5) # Wait for worker thread
    server.shutdown()
    
    assert server.handle_request.called


def test_server_has_transport_field():
    server = LocalSearchMCPServer("/tmp/ws")
    assert hasattr(server, "transport")
    assert server.transport is None
    server.shutdown()


def test_server_run_uses_original_stdout_stream(monkeypatch):
    class _NoCloseBytesIO(io.BytesIO):
        def close(self):
            # Keep test buffers readable after server shutdown.
            pass

    class _TextWithBuffer:
        def __init__(self, buffer_obj):
            self.buffer = buffer_obj

    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test"}},
    }
    body = json.dumps(req).encode("utf-8")
    framed = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body

    fake_stdin_buf = _NoCloseBytesIO(framed)
    fake_stdout_buf = _NoCloseBytesIO()
    original_stdout_buf = _NoCloseBytesIO()

    monkeypatch.setattr(server_mod.sys, "stdin", _TextWithBuffer(fake_stdin_buf))
    monkeypatch.setattr(server_mod.sys, "stdout", _TextWithBuffer(fake_stdout_buf))

    server = LocalSearchMCPServer("/tmp/ws")
    server._original_stdout = _TextWithBuffer(original_stdout_buf)
    server.run()

    written_original = original_stdout_buf.getvalue()
    written_redirected = fake_stdout_buf.getvalue()
    assert b"Content-Length:" in written_original
    assert b"\"id\": 1" in written_original
    assert written_redirected == b""


@pytest.mark.gate
def test_server_tools_call_uses_session_and_returns_result():
    server = LocalSearchMCPServer("/tmp/ws")
    fake_session = MagicMock()
    fake_session.db = MagicMock()
    fake_session.db.engine = MagicMock()
    fake_session.indexer = MagicMock()
    fake_session.config_data = {"workspace_roots": ["/tmp/ws"]}
    server.registry.get_or_create = MagicMock(return_value=fake_session)
    server._tool_registry.execute = MagicMock(return_value={"ok": True})

    result = server.handle_tools_call({"name": "status", "arguments": {}})

    assert result == {"ok": True}
    server.registry.get_or_create.assert_called_once_with("/tmp/ws")
    server.shutdown()


@pytest.mark.gate
def test_server_serializes_transport_writes():
    server = LocalSearchMCPServer("/tmp/ws")
    server.handle_request = MagicMock(return_value={"jsonrpc": "2.0", "id": 1, "result": {}})

    class SlowTransport:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def write_message(self, *_args, **_kwargs):
            with self.lock:
                self.active += 1
                if self.active > self.max_active:
                    self.max_active = self.active
            time.sleep(0.03)
            with self.lock:
                self.active -= 1

    server.transport = SlowTransport()
    req = {"id": 1, "method": "ping", "_sari_framing_mode": "content-length"}

    t1 = threading.Thread(target=server._handle_and_respond, args=(req,))
    t2 = threading.Thread(target=server._handle_and_respond, args=(req,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert server.transport.max_active == 1
    server.shutdown()
