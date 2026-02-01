
import pytest
from app.indexer import _extract_symbols
from app.db import LocalSearchDB
from mcp.tools.read_symbol import execute_read_symbol
from unittest.mock import MagicMock

class TestReviewRound1:
    """Round 1: Deep dive into Symbol Block Parsing & read_symbol tool."""

    def test_python_nested_blocks(self):
        """Test 1: Verify correct end_line detection for nested Python functions/classes."""
        code = """
class Outer:
    def method_a(self):
        x = 1
        if True:
            y = 2
    
    def method_b(self):
        return "b"

def global_func():
    pass
"""
        symbols = _extract_symbols("test.py", code.strip())
        # Symbol list: [Outer, method_a, method_b, global_func]
        
        # Helper to find symbol by name
        def get_sym(name):
            return next((s for s in symbols if s[1] == name), None)

        outer = get_sym("Outer")
        method_a = get_sym("method_a")
        method_b = get_sym("method_b")
        glob = get_sym("global_func")

        assert outer, "Outer class not found"
        assert method_a, "method_a not found"
        
        # Logic check: method_a is inside Outer, so it should end before method_b starts?
        # Or at least method_a block should cover its body.
        # Lines (0-based in list, 1-based in result):
        # 1: class Outer:
        # 2:     def method_a(self):
        # ...
        # 7:     def method_b(self):
        
        # method_a start: 2. End should be 6 (before method_b definition) or 5.
        assert method_a[3] == 2 # Start line
        assert method_a[4] >= 5 # End line (at least body included)
        assert method_a[4] < method_b[3] # Should end before method_b starts

    def test_js_brace_counting(self):
        """Test 2: Verify brace counting for JS functions."""
        code = """
function foo() {
    if (true) {
        return { x: 1 };
    }
}
class Bar {
    method() {}
}
"""
        symbols = _extract_symbols("test.js", code.strip())
        foo = next((s for s in symbols if s[1] == "foo"), None)
        bar = next((s for s in symbols if s[1] == "Bar"), None)

        assert foo
        assert foo[4] == 5 # Ends at closing brace of foo
        assert bar
        assert bar[4] == 8 # Ends at closing brace of Bar

    def test_broken_syntax_handling(self):
        """Test 3: Verify parser doesn't crash on unclosed blocks."""
        code = """
def broken():
    print("This function never ends...
"""
        # Should gracefully handle EOF
        symbols = _extract_symbols("broken.py", code.strip())
        broken = symbols[0]
        assert broken[1] == "broken"
        assert broken[4] >= 2 # Should extend to EOF (2 lines)

    def test_read_symbol_tool_not_found(self):
        """Test 4: read_symbol tool should handle missing symbols gracefully."""
        mock_db = MagicMock()
        mock_db.get_symbol_block.return_value = None # Simulate not found
        mock_logger = MagicMock()
        
        args = {"path": "missing.py", "name": "Ghost"}
        result = execute_read_symbol(args, mock_db, mock_logger)
        
        assert result["isError"] is True
        assert "not found" in result["content"][0]["text"]
