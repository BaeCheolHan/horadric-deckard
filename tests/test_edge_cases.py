import json
import pytest
import io
import os
from unittest.mock import MagicMock, patch
from sari.mcp.server import LocalSearchMCPServer
from sari.mcp.proxy import _read_mcp_message

class TestEdgeCases:
    
    # 1. Protocol Version Edge Cases
    def test_protocol_missing(self):
        server = LocalSearchMCPServer("/tmp")
        # Missing protocolVersion -> should use default
        resp = server.handle_initialize({})
        assert resp["protocolVersion"] == server.PROTOCOL_VERSION

    def test_protocol_empty(self):
        server = LocalSearchMCPServer("/tmp")
        # Empty protocolVersion -> should use default
        resp = server.handle_initialize({"protocolVersion": ""})
        assert resp["protocolVersion"] == server.PROTOCOL_VERSION

    def test_protocol_unsupported_format(self):
        server = LocalSearchMCPServer("/tmp")
        # Malformed version should fall back to default for compatibility
        resp = server.handle_initialize({"protocolVersion": "v1.0-alpha"})
        assert resp["protocolVersion"] == server.PROTOCOL_VERSION

    # 2. Stdio Framing Edge Cases
    def test_content_length_whitespace(self):
        # Header with leading/trailing whitespace
        msg = b'{"jsonrpc": "2.0"}'
        stdin = io.BytesIO(b'Content-Length:   ' + str(len(msg)).encode('ascii') + b'  \r\n\r\n' + msg)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is not None
            assert result[0] == msg

    def test_content_length_negative(self):
        msg = b'{"jsonrpc": "2.0"}'
        stdin = io.BytesIO(b'Content-Length: -10\r\n\r\n' + msg)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is None

    def test_content_length_malformed(self):
        msg = b'{"jsonrpc": "2.0"}'
        stdin = io.BytesIO(b'Content-Length: abc\r\n\r\n' + msg)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is None

    def test_incomplete_body(self):
        # Body shorter than Content-Length
        msg = b'{"jsonrpc": "2.0"}'
        stdin = io.BytesIO(b'Content-Length: 100\r\n\r\n' + msg)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is None # Should fail to read full body

    def test_extra_headers(self):
        # Multiple headers, Content-Length in the middle
        msg = b'{"jsonrpc": "2.0"}'
        headers = (
            b'X-Foo: bar\r\n'
            b'Content-Length: ' + str(len(msg)).encode('ascii') + b'\r\n'
            b'Content-Type: application/json\r\n'
            b'\r\n'
        )
        stdin = io.BytesIO(headers + msg)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is not None
            assert result[0] == msg

    def test_hard_exclude_list(self):
        from sari.core.indexer.scanner import Scanner
        mock_cfg = MagicMock()
        mock_cfg.exclude_dirs = []
        scanner = Scanner(mock_cfg)
        assert ".git" in scanner.hard_exclude_dirs
        assert "node_modules" in scanner.hard_exclude_dirs
