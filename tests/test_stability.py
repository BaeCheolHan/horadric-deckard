import json
import pytest
import io
import os
from unittest.mock import MagicMock, patch
from sari.mcp.server import LocalSearchMCPServer
from sari.mcp.proxy import _read_mcp_message

class TestStability:
    
    def test_protocol_version_negotiation_success(self):
        server = LocalSearchMCPServer("/tmp")
        # Test 2024-11-05
        resp = server.handle_initialize({"protocolVersion": "2024-11-05"})
        assert resp["protocolVersion"] == "2024-11-05"
        
        # Test 2025-03-26
        resp = server.handle_initialize({"protocolVersion": "2025-03-26"})
        assert resp["protocolVersion"] == "2025-03-26"

        # Test 2025-06-18 (Codex MCP client)
        resp = server.handle_initialize({"protocolVersion": "2025-06-18"})
        assert resp["protocolVersion"] == "2025-06-18"

    def test_protocol_version_negotiation_failure(self):
        server = LocalSearchMCPServer("/tmp")
        # Unsupported version falls back to server default
        resp = server.handle_initialize({"protocolVersion": "2099-01-01"})
        assert resp["protocolVersion"] == server.PROTOCOL_VERSION

    def test_protocol_version_via_handle_request(self):
        server = LocalSearchMCPServer("/tmp")
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2099-01-01"}
        }
        resp = server.handle_request(req)
        assert "result" in resp
        assert resp["result"]["protocolVersion"] == server.PROTOCOL_VERSION

    def test_proxy_framing_strict(self):
        # Default: JSONL accepted
        stdin = io.BytesIO(b'{"jsonrpc": "2.0"}\n')
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is not None
            assert result[0] == b'{"jsonrpc": "2.0"}'
            assert result[1] == "jsonl"

        # Content-Length accepted
        msg = b'{"jsonrpc": "2.0"}'
        header = f'Content-Length: {len(msg)}\r\n\r\n'.encode('ascii')
        stdin = io.BytesIO(header + msg)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is not None
            assert result[0] == msg
            assert result[1] == "framed"
