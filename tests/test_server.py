import pytest
import json
import threading
from unittest.mock import MagicMock, patch
from sari.mcp.server import LocalSearchMCPServer

def test_server_handle_initialize():
    server = LocalSearchMCPServer("/tmp/ws")
    params = {"rootUri": "file:///tmp/ws2"}
    resp = server.handle_initialize(params)
    assert resp["protocolVersion"] == "2025-11-25"
    assert "tools" in resp["capabilities"]
    assert "prompts" in resp["capabilities"]
    assert "resources" in resp["capabilities"]
    assert server.workspace_root == "/tmp/ws2"

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
