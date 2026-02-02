import unittest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound7AdvancedPython(unittest.TestCase):

    def test_01_nested_class(self):
        code = """
class Outer:
    class Inner:
        pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        inner = next((s for s in symbols if s[1] == "Inner"), None)
        self.assertIsNotNone(inner)
        self.assertEqual(inner[6], "Outer") # parent_name

    def test_02_class_method_parent(self):
        code = """
class MyController:
    def get_data(self):
        pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        method = next((s for s in symbols if s[1] == "get_data"), None)
        self.assertEqual(method[6], "MyController")
        self.assertEqual(method[2], "method")

    def test_03_nested_function(self):
        code = """
def outer_func():
    def inner_func():
        pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        inner = next((s for s in symbols if s[1] == "inner_func"), None)
        self.assertEqual(inner[6], "outer_func")

    def test_04_complex_decorator_args(self):
        code = """
@app.route("/api/v1/items", methods=["GET", "POST"], endpoint="items")
def handle_items():
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "handle_items"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/api/v1/items")

    def test_05_decorator_chain_ordering(self):
        code = """
@validate_user
@app.post("/submit")
@log_action
async def submit_data():
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "submit_data"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/submit")

    def test_06_async_generator(self):
        code = """
async def get_stream():
    yield "data"
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "get_stream"), None)
        self.assertIsNotNone(target)

    def test_07_multiline_numpy_docstring(self):
        code = '''
def complex_calc(a, b):
    """
    Perform a complex calculation.

    Parameters
    ----------
    a : int
        The first value.
    b : int
        The second value.

    Returns
    -------
    int
        The result.
    """
    return a + b
'''
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "complex_calc"), None)
        doc = target[8]
        self.assertIn("Parameters", doc)
        self.assertIn("The first value.", doc)

    def test_08_class_attribute_vs_method(self):
        # Attributes shouldn't be captured as methods
        code = """
class Config:
    MAX_SIZE = 100
    def reset(self):
        pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        # Should NOT find MAX_SIZE
        target = next((s for s in symbols if s[1] == "MAX_SIZE"), None)
        self.assertIsNone(target)
        self.assertIsNotNone(next(s for s in symbols if s[1] == "reset"))

    def test_09_main_block_definitions(self):
        code = """
if __name__ == "__main__":
    def local_tool():
        pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "local_tool"), None)
        self.assertIsNotNone(target)

    def test_10_lambda_ignore(self):
        code = "add = lambda x, y: x + y"
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "add"), None)
        self.assertIsNone(target)

if __name__ == '__main__':
    unittest.main()
