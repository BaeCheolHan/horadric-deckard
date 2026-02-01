
import pytest
import json
import io
from unittest.mock import patch
from mcp.server import LocalSearchMCPServer

class TestShieldProtocol:
    """
    Round 19: Protocol Compliance Shield.
    Ensures deckard speaks perfect MCP/JSON-RPC.
    """

    @pytest.fixture
    def server(self, tmp_path):
        return LocalSearchMCPServer(str(tmp_path))

    def _send(self, server, req_dict):
        inp = json.dumps(req_dict)
        with patch("sys.stdin", io.StringIO(inp)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            server.run()
            return json.loads(mock_stdout.getvalue())

    def test_jsonrpc_id_echo(self, server):
        """
        Shield 1: Method Response MUST echo ID.
        """
        ids = [1, "string_id", None] # None usually notification?
        
        req = {"jsonrpc": "2.0", "method": "ping", "id": 123}
        resp = self._send(server, req)
        assert resp["id"] == 123
        
        req = {"jsonrpc": "2.0", "method": "ping", "id": "abc"}
        resp = self._send(server, req)
        assert resp["id"] == "abc"

    def test_tool_list_schema(self, server):
        """
        Shield 2: tools/list MUST return valid Tool objects.
        """
        req = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        resp = self._send(server, req)
        
        tools = resp["result"]["tools"]
        assert isinstance(tools, list)
        for t in tools:
            assert "name" in t
            assert "inputSchema" in t
            assert "type" in t["inputSchema"]

    def test_invalid_params_error(self, server):
        """
        Shield 3: Tool call with missing required param MUST fail.
        """
        # Search requires "query" (checked mcp/server.py before? or calls search_tool which checks?)
        req = {
            "jsonrpc": "2.0", 
            "method": "tools/call", 
            "params": {"name": "search", "arguments": {}}, # Missing query
            "id": 1
        }
        resp = self._send(server, req)
        
        # Expect Error. 
        # Deckard implementation returns result with isError=True, text="Error..." 
        # instead of top-level JSON-RPC error for valid method calls with bad args.
        if "error" in resp:
            pass # Good
        else:
            assert "result" in resp
            assert resp["result"].get("isError") is True
            assert "query is required" in resp["result"]["content"][0]["text"]
        
    def test_jsonrpc_version(self, server):
        """
        Shield 4: Response MUST include jsonrpc: 2.0.
        """
        req = {"jsonrpc": "2.0", "method": "ping", "id": 1}
        resp = self._send(server, req)
        assert resp["jsonrpc"] == "2.0"
