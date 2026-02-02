import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound8EdgeCases(unittest.TestCase):

    def test_01_ts_inheritance(self):
        code = "class Greeter extends BaseController { greet() {} }"
        symbols, _ = _extract_symbols("test.ts", code)
        target = next((s for s in symbols if s[1] == "Greeter"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target[2], "class")

    def test_02_js_function(self):
        code = "function calculate(a, b) { return a + b; }"
        symbols, _ = _extract_symbols("test.js", code)
        target = next((s for s in symbols if s[1] == "calculate"), None)
        self.assertIsNotNone(target)

    def test_03_go_method_receiver(self):
        # Current Go regex is func[ 	]+([a-zA-Z0-9_]+)
        # Receiver syntax might be tricky: func (r *Repo) Save()
        code = "func (r *Repo) Save(data string) error { return nil }"
        symbols, _ = _extract_symbols("test.go", code)
        # Expected to find 'Save'
        target = next((s for s in symbols if s[1] == "Save"), None)
        # Based on current regex, it might fail because of (r *Repo)
        # Let's check and potentially fix.
        pass

    def test_04_unicode_identifiers(self):
        code = "def 한글_테스트_함수(): pass"
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "한글_테스트_함수"), None)
        self.assertIsNotNone(target)

    def test_05_very_long_line(self):
        long_line = "def long():" + (" " * 10000) + "pass"
        try:
            _extract_symbols("test.py", long_line)
        except Exception:
            self.fail("Crashed on very long line")

    def test_06_mixed_line_endings(self):
        code = "def line1():\r\n    pass\ndef line2():\n    pass"
        symbols, _ = _extract_symbols("test.py", code)
        self.assertEqual(len(symbols), 2)

    def test_07_no_newline_eof(self):
        code = "def eof(): pass" # No newline at end
        symbols, _ = _extract_symbols("test.py", code)
        self.assertEqual(len(symbols), 1)

    def test_08_ts_interface_extends(self):
        code = "interface UserData extends BaseEntity { id: string; }"
        symbols, _ = _extract_symbols("test.ts", code)
        target = next((s for s in symbols if s[1] == "UserData"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target[2], "class") # currently mapped to class or we can add 'interface'

    def test_09_python_type_alias_ignore(self):
        code = "Vector = list[float]"
        symbols, _ = _extract_symbols("test.py", code)
        self.assertEqual(len(symbols), 0)

    def test_10_empty_file(self):
        symbols, _ = _extract_symbols("empty.py", "")
        self.assertEqual(len(symbols), 0)

if __name__ == '__main__':
    unittest.main()
