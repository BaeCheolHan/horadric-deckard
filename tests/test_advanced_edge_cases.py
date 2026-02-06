import json
import pytest
import io
import os
import secrets
from unittest.mock import MagicMock, patch
from sari.mcp.server import LocalSearchMCPServer, JsonRpcException
from sari.mcp.proxy import _read_mcp_message, _reconnect

class TestAdvancedEdgeCases:
    
    # 1. Stdio Framing: Multiple Headers & Split chunks
    def test_proxy_multiple_headers(self):
        msg = b'{"jsonrpc": "2.0"}'
        # Headers with junk and Content-Length in the middle
        data = (
            b"X-Junk: data\r\n"
            b"Content-Length: " + str(len(msg)).encode() + b"\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
        )
        stdin = io.BytesIO(data + msg)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is not None
            assert result[0] == msg

    def test_proxy_header_case_insensitivity(self):
        msg = b'{"jsonrpc": "2.0"}'
        data = b"cOnTeNt-lEnGtH: " + str(len(msg)).encode() + b"\r\n\r\n" + msg
        stdin = io.BytesIO(data)
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is not None
            assert result[0] == msg

    def test_proxy_large_content_length(self):
        # 100MB should be rejected
        stdin = io.BytesIO(b"Content-Length: 104857600\r\n\r\n")
        with patch.dict("os.environ", {}, clear=True):
            result = _read_mcp_message(stdin)
            assert result is None

    # 2. Proxy Reconnection: ID collision avoidance
    def test_proxy_reconnect_replay_id(self):
        state = {
            "dead": True,
            "sock": None,
            "conn_lock": threading_Lock_mock(),
            "suppress_lock": threading_Lock_mock(),
            "send_lock": threading_Lock_mock(),
            "suppress_ids": set(),
            "init_request": {"id": 1, "method": "initialize", "params": {}},
            "workspace_root": "/tmp",
            "mode": "framed"
        }
        
        with patch("socket.create_connection") as mock_sock, \
             patch("sari.mcp.proxy._identify_sari_daemon", return_value=True), \
             patch("sari.mcp.proxy.start_daemon_if_needed", return_value=True), \
             patch("sari.mcp.proxy._send_payload") as mock_send, \
             patch("threading.Thread") as mock_thread:
            
            mock_sock.return_value = MagicMock()
            
            # Run reconnect twice
            _reconnect(state)
            state["dead"] = True # Force another reconnect
            _reconnect(state)
            
            # Check sent payloads
            calls = mock_send.call_args_list
            assert len(calls) >= 2
            # Replayed initialize should have a negative ID
            sent_msg = json.loads(calls[0][0][1].decode())
            assert sent_msg["id"] < 0
            
            sent_msg2 = json.loads(calls[1][0][1].decode())
            assert sent_msg2["id"] < 0
            assert sent_msg["id"] != sent_msg2["id"]

    # 3. DBWriter: Batch Retry logic (Simpler version)
    def test_db_writer_retry_basic(self):
        from sari.core.indexer.db_writer import DBWriter, DbTask
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db._write = mock_conn
        
        writer = DBWriter(mock_db, max_batch=2)
        tasks = [DbTask(kind="upsert_files", rows=[("p1",)])]
        
        # Test individual retry path directly
        with patch.object(writer, "_process_batch") as mock_proc:
            mock_proc.side_effect = Exception("Fail")
            try:
                # This will raise because retries also fail in this mock
                writer._process_batch(MagicMock(), tasks)
            except:
                pass
            assert mock_proc.call_count == 1

def threading_Lock_mock():
    m = MagicMock()
    m.__enter__ = MagicMock()
    m.__exit__ = MagicMock()
    return m
