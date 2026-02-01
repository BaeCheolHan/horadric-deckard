
import pytest
import json
import io
import sys
from unittest.mock import patch, MagicMock
from mcp.server import LocalSearchMCPServer

class TestShieldResilience:
    """
    Round 14: Resilience Shield.
    Ensures server robustness against bad inputs and crashes.
    """

    @pytest.fixture
    def server(self, tmp_path):
        return LocalSearchMCPServer(str(tmp_path))

    def test_malformed_json_resilience(self, server):
        """
        Shield 1: Server MUST NOT crash on invalid JSON.
        It must try next line.
        """
        bad_input = "{ broken json \n" + json.dumps({"jsonrpc": "2.0", "method": "ping", "id": 1})
        
        # Mock sys.stdin
        with patch("sys.stdin", io.StringIO(bad_input)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            
            # Start server (it loops until stdin ends)
            # We mock run logic or call it? 
            # If we call run(), it blocks.
            # But stdin is finite StringIO, so loop finishes.
            
            server.run()
            
            output = mock_stdout.getvalue()
            lines = output.strip().splitlines()
            
            # First line: Error response for bad json
            resp1 = json.loads(lines[0])
            assert resp1["error"]["code"] == -32700
            
            # Second line: Success response for ping
            resp2 = json.loads(lines[1])
            assert resp2["result"] == {}

    def test_unknown_method_resilience(self, server):
        """
        Shield 2: Unknown method returns error, does not crash.
        """
        req = {"jsonrpc": "2.0", "method": "explode", "id": 99}
        input_str = json.dumps(req)
        
        with patch("sys.stdin", io.StringIO(input_str)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
             
            server.run()
            
            output = mock_stdout.getvalue()
            resp = json.loads(output)
            assert resp["error"]["code"] == -32601 # Method not found

    def test_tool_crash_resilience(self, server):
        """
        Shield 3: Internal tool crash returns Internal Error, does not crash server.
        """
        # We patch `handle_tools_call` to raise Exception
        with patch.object(server, "handle_tools_call", side_effect=ValueError("Boom")):
            req = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "search"}, "id": 1}
            input_str = json.dumps(req)
            
            with patch("sys.stdin", io.StringIO(input_str)), \
                 patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                 
                server.run()
                
                output = mock_stdout.getvalue()
                resp = json.loads(output)
                assert resp["error"]["code"] == -32000
                assert "Boom" in resp["error"]["message"]

    def test_large_payload_resilience(self, server):
        """
        Shield 4: Huge payload handling.
        """
        huge_str = "x" * 1000000 # 1MB
        req = {"jsonrpc": "2.0", "method": "ping", "params": {"data": huge_str}, "id": 1}
        # Dump might take memory, but verify it processes.
        input_str = json.dumps(req)
        
        with patch("sys.stdin", io.StringIO(input_str)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
             
            server.run()
            
            output = mock_stdout.getvalue()
            resp = json.loads(output)
            # Should succeed (ping returns {})
            assert resp["result"] == {}

    def test_unicode_input_resilience(self, server):
        """
        Shield 5: Unicode input handling.
        """
        req = {"jsonrpc": "2.0", "method": "ping", "params": {"data": "한글"}, "id": 1}
        input_str = json.dumps(req)
        
        with patch("sys.stdin", io.StringIO(input_str)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
             
            server.run()
            resp = json.loads(mock_stdout.getvalue())
            assert resp["result"] == {}
