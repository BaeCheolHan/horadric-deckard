import unittest
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.indexer import _extract_symbols

class TestRound1PythonParsing(unittest.TestCase):
    
    def test_01_fastapi_basic_get(self):
        code = """
from fastapi import FastAPI
app = FastAPI()

@app.get("/items")
def read_items():
    return []
"""
        symbols, _ = _extract_symbols("test.py", code)
        self.assertTrue(len(symbols) > 0)
        # Find 'read_items'
        target = next((s for s in symbols if s[1] == "read_items"), None)
        self.assertIsNotNone(target)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/items")
        self.assertIn("GET", meta.get("annotations", []))

    def test_02_flask_route(self):
        code = """
from flask import Flask
app = Flask(__name__)

@app.route("/hello")
def hello_world():
    return "Hello"
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "hello_world"), None)
        self.assertIsNotNone(target)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/hello")
        self.assertIn("ROUTE", meta.get("annotations", []))

    def test_03_router_object_method(self):
        code = """
@router.post("/users/new")
def create_user(user: User):
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "create_user"), None)
        self.assertIsNotNone(target)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/users/new")
        self.assertIn("POST", meta.get("annotations", []))

    def test_04_path_with_variables(self):
        code = """
@app.put("/items/{item_id}")
def update_item(item_id: int):
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "update_item"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/items/{item_id}")

    def test_05_nested_decorators(self):
        # The parser should find the http path even if other decorators exist
        code = """
@auth_required
@app.delete("/items/{id}")
@log_request
def delete_item(id: int):
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "delete_item"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/items/{id}")

    def test_06_async_function(self):
        code = """
@app.patch("/async/task")
async def do_something_async():
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "do_something_async"), None)
        self.assertIsNotNone(target)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/async/task")

    def test_07_decorator_without_args(self):
        # Should be ignored or handled gracefully without crash
        code = """
@simple_decorator
def simple_func():
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "simple_func"), None)
        meta = json.loads(target[7])
        self.assertIsNone(meta.get("http_path"))

    def test_08_irrelevant_decorators(self):
        # Verify irrelevant decorators don't trigger http_path
        code = """
@lru_cache(maxsize=128)
def cached_func():
    pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "cached_func"), None)
        meta = json.loads(target[7])
        self.assertIsNone(meta.get("http_path"))

    def test_09_class_method_route(self):
        # API route on a method inside a class (common in some frameworks)
        code = """
class UserView:
    @app.get("/users/me")
    def get_me(self):
        pass
"""
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "get_me"), None)
        self.assertEqual(target[2], "method") # Kind should be method
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/users/me")

    def test_10_invalid_syntax_resilience(self):
        # Parser should not crash on syntax errors, just skip or partial parse
        code = """
@app.get("/broken"
def broken_func():
    pass
"""
        # AST parser might fail, _extract_symbols catches exception and returns empty or partial
        try:
            symbols, _ = _extract_symbols("test.py", code)
        except Exception:
            self.fail("Indexer crashed on invalid syntax")

if __name__ == '__main__':
    unittest.main()
