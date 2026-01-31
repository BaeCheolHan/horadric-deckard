#!/usr/bin/env python3
"""
Unit tests for Local Search MCP Server

Usage:
  python3 -m pytest .codex/tools/local-search/mcp/test_server.py -v
  # or
  python3 .codex/tools/local-search/mcp/test_server.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add paths for imports
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "app"))

from server import LocalSearchMCPServer


def test_initialize():
    """Test MCP initialize response."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        
        result = server.handle_initialize({})
        
        assert result["protocolVersion"] == "2025-11-25"
        assert result["serverInfo"]["name"] == "local-search"
        assert result["serverInfo"]["version"] == "2.5.0"
        assert "tools" in result["capabilities"]


def test_tools_list():
    """Test tools/list response."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        
        result = server.handle_tools_list({})
        
        tools = result["tools"]
        tool_names = [t["name"] for t in tools]
        
        assert "search" in tool_names
        assert "status" in tool_names
        assert "repo_candidates" in tool_names
        
        # Check search tool schema
        search_tool = next(t for t in tools if t["name"] == "search")
        assert "query" in search_tool["inputSchema"]["properties"]
        assert "query" in search_tool["inputSchema"]["required"]


def test_handle_request_initialize():
    """Test full request handling for initialize."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
        
        response = server.handle_request(request)
        
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["protocolVersion"] == "2025-11-25"


def test_handle_request_tools_list():
    """Test full request handling for tools/list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        
        response = server.handle_request(request)
        
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert "result" in response
        assert "tools" in response["result"]


def test_handle_request_unknown_method():
    """Test error handling for unknown method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "unknown/method",
            "params": {},
        }
        
        response = server.handle_request(request)
        
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "error" in response
        assert response["error"]["code"] == -32601


def test_handle_notification_no_response():
    """Test that notifications (no id) don't return a response."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        
        # Notification has no "id" field
        request = {
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {},
        }
        
        response = server.handle_request(request)
        
        assert response is None


def test_tool_status():
    """Test status tool execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        server._ensure_initialized()
        
        result = server._tool_status({})
        
        assert "content" in result
        assert len(result["content"]) > 0
        assert result["content"][0]["type"] == "text"
        
        status = json.loads(result["content"][0]["text"])
        assert "index_ready" in status
        assert "workspace_root" in status


def test_tool_search_empty_query():
    """Test search tool with empty query returns error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server = LocalSearchMCPServer(tmpdir)
        server._ensure_initialized()
        
        result = server._tool_search({"query": ""})
        
        assert result.get("isError") is True


def run_tests():
    """Run all tests without pytest."""
    import traceback
    
    tests = [
        test_initialize,
        test_tools_list,
        test_handle_request_initialize,
        test_handle_request_tools_list,
        test_handle_request_unknown_method,
        test_handle_notification_no_response,
        test_tool_status,
        test_tool_search_empty_query,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            print(f"✓ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__}")
            traceback.print_exc()
            failed += 1
    
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
