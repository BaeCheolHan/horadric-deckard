import unittest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound9AdvancedParser(unittest.TestCase):

    def test_01_string_literal_protection(self):
        code = 'String s = "class Fake {}";'
        symbols, _ = _extract_symbols("test.java", code)
        self.assertEqual(len(symbols), 0, "Should not detect symbols inside string literals")

    def test_02_go_receiver_support(self):
        code = "func (r *Database) Query(q string) error { return nil }"
        symbols, _ = _extract_symbols("test.go", code)
        target = next((s for s in symbols if s[1] == "Query"), None)
        self.assertIsNotNone(target, "Should detect Go methods with receivers")

    def test_03_cpp_struct_enum(self):
        code = "struct Point { int x; int y; };\nenum Color { RED, BLUE };"
        symbols, _ = _extract_symbols("test.cpp", code)
        self.assertTrue(any(s[1] == "Point" and s[2] == "struct" for s in symbols))
        self.assertTrue(any(s[1] == "Color" and s[2] == "enum" for s in symbols))

    def test_04_annotation_aggregation(self):
        code = """
@Service
@Transactional
@RequestMapping(\"/api\")
public class MyService {}
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "MyService"), None)
        meta = json.loads(target[7])
        annos = meta.get("annotations", [])
        self.assertIn("SERVICE", annos)
        self.assertIn("TRANSACTIONAL", annos)
        self.assertEqual(meta.get("http_path"), "/api")

    def test_05_js_export_async(self):
        code = "export async function fetchData() {}"
        symbols, _ = _extract_symbols("test.js", code)
        target = next((s for s in symbols if s[1] == "fetchData"), None)
        self.assertIsNotNone(target)

    def test_06_trailing_comments(self):
        code = "class ValidClass {} // This is a real class"
        symbols, _ = _extract_symbols("test.java", code)
        self.assertTrue(any(s[1] == "ValidClass" for s in symbols))

    def test_07_single_quote_protection(self):
        code = "const s = 'class Fake {}';"
        symbols, _ = _extract_symbols("test.js", code)
        self.assertEqual(len(symbols), 0)

    def test_08_method_return_array(self):
        code = "public String[] listItems() { return null; }"
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "listItems"), None)
        self.assertIsNotNone(target)

    def test_09_multiple_implements_messy(self):
        code = "class Boss implements Manager ,  Leader,Worker {}"
        _, relations = _extract_symbols("test.java", code)
        targets = {r[3] for r in relations if r[1] == "Boss"}
        self.assertIn("Manager", targets)
        self.assertIn("Leader", targets)
        self.assertIn("Worker", targets)

    def test_10_go_simple_function(self):
        code = "func Hello() {}"
        symbols, _ = _extract_symbols("test.go", code)
        self.assertTrue(any(s[1] == "Hello" for s in symbols))

if __name__ == '__main__':
    unittest.main()
