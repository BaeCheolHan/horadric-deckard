import sys
from pathlib import Path
import json
import unittest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import LocalSearchDB
from app.indexer import _extract_symbols

class TestRound1(unittest.TestCase):
    def test_1_1_python_decorators(self):
        content = """
@decorator1
@decorator2(arg='val')
def my_func():
    \"\"\"My Docstring\"\"\"
    pass
"""
        symbols = _extract_symbols("test.py", content)
        meta = json.loads(symbols[0][7])
        self.assertIn("@decorator1", meta["decorators"])
        self.assertIn("@decorator2(...)", meta["decorators"])

    def test_1_2_java_implements(self):
        content = """
@Service
public class UserServiceImpl implements UserService {
    public void save() {}
}
"""
        symbols = _extract_symbols("UserServiceImpl.java", content)
        # Check if annotations are captured
        meta = json.loads(symbols[0][7])
        self.assertIn("@Service", meta["annotations"])

    def test_1_3_java_multi_mapping(self):
        content = """
@RequestMapping({"/api/v1", "/api/v2"})
public class ApiController {}
"""
        symbols = _extract_symbols("ApiController.java", content)
        # Note: Current implementation might only catch first one or raw string. 
        # This test identifies if we need to improve regex.
        meta = json.loads(symbols[0][7])
        self.assertTrue("http_path" in meta)

    def test_1_4_python_async_doc(self):
        content = """
async def async_task():
    \"\"\"Async Doc\"\"\"
    return 1
"""
        symbols = _extract_symbols("async.py", content)
        self.assertEqual(symbols[0][8].strip(), "Async Doc")

    def test_1_10_parent_name(self):
        content = """
class MyClass:
    def my_method(self):
        pass
"""
        symbols = _extract_symbols("parent.py", content)
        # Index 0 is MyClass, Index 1 is my_method
        method = next(s for s in symbols if s[1] == "my_method")
        self.assertEqual(method[6], "MyClass")

if __name__ == "__main__":
    unittest.main()
