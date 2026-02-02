import sys
from pathlib import Path
import json
import unittest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.indexer import _extract_symbols

class TestRound4(unittest.TestCase):
    def test_4_1_python_call_extraction(self):
        content = """
def func_a():
    pass

def func_b():
    func_a()
    obj.method_c()
"""
        symbols, relations = _extract_symbols("test.py", content)
        # Check if relations from func_b are captured
        b_calls = [r for r in relations if r[1] == "func_b"]
        targets = [r[3] for r in b_calls]
        self.assertIn("func_a", targets)
        self.assertIn("method_c", targets)

    def test_4_2_java_call_extraction(self):
        content = """
public class MyService {
    public void process() {
        validate();
        db.save();
    }
    private void validate() {}
}
"""
        symbols, relations = _extract_symbols("MyService.java", content)
        proc_calls = [r for r in relations if r[1] == "process"]
        targets = [r[3] for r in proc_calls]
        self.assertIn("validate", targets)
        self.assertIn("save", targets)

    def test_4_3_docstring_cleanup(self):
        content = """
/**
 * Hello
 * World
 */
def hello(): pass
"""
        symbols, relations = _extract_symbols("hello.py", content)
        self.assertEqual(symbols[0][8], "Hello\nWorld")

if __name__ == "__main__":
    unittest.main()

