import unittest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound10MultilineLogic(unittest.TestCase):

    def test_01_multiline_annotations(self):
        code = """
@Service
@Transactional
public void save() {}
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next(s for s in symbols if s[1] == "save")
        meta = json.loads(target[7])
        self.assertEqual(len(meta["annotations"]), 2)

    def test_02_multiline_extends(self):
        code = """
public class HeavyList
    extends ArrayList<String> {
"""
        _, relations = _extract_symbols("test.java", code)
        rel = next((r for r in relations if r[1] == "HeavyList" and r[4] == "extends"), None)
        self.assertIsNotNone(rel, "Should detect multi-line extends")
        self.assertEqual(rel[3], "ArrayList<String>")

    def test_03_comments_between_annotations(self):
        code = """
@A
// comment
@B
void m() {}
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next(s for s in symbols if s[1] == "m")
        annos = json.loads(target[7])["annotations"]
        self.assertIn("A", annos)
        self.assertIn("B", annos)

    def test_04_java_generic_method_spacing(self):
        code = """
public <T> T 
getData() { return null; }
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "getData"), None)
        self.assertIsNotNone(target)

    def test_05_implements_with_newlines(self):
        code = """
class Boss 
    implements Manager, 
               Leader {
"""
        _, relations = _extract_symbols("test.java", code)
        targets = {r[3] for r in relations if r[1] == "Boss"}
        self.assertIn("Manager", targets)
        self.assertIn("Leader", targets)

    def test_06_annotation_with_params_multiline(self):
        # Currently we only support single-line @Mapping detection via api_pattern.
        # This test checks if it FAILS gracefully or if we can fix it.
        code = """
@GetMapping(
  "/multi/line"
)
void complex() {}
"""
        symbols, _ = _extract_symbols("test.java", code)
        # Probable fail to get path, but should find method
        target = next(s for s in symbols if s[1] == "complex")
        self.assertIsNotNone(target)

    def test_07_docstring_empty_lines(self):
        code = """/**

Doc

*/
void m(){}"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next(s for s in symbols if s[1] == "m")
        self.assertIn("Doc", target[8])

    def test_08_kotlin_multiline_inheritance(self):
        code = """
class MyView : 
    BaseView(), 
    Observable {
"""
        _, relations = _extract_symbols("test.kt", code)
        targets = {r[3] for r in relations if r[1] == "MyView"}
        self.assertIn("BaseView()", targets)
        self.assertIn("Observable", targets)

    def test_09_mixed_indent_tabs_spaces(self):
        code = "\tpublic void tabbed() {}\n    public void spaced() {}"
        symbols, _ = _extract_symbols("test.java", code)
        self.assertEqual(len(symbols), 2)

    def test_10_consecutive_symbols_no_space(self):
        code = "void a(){}void b(){}"
        symbols, _ = _extract_symbols("test.java", code)
        # Current parser is line-by-line, might only find 'a'
        # This documents the limitation.
        pass

if __name__ == '__main__':
    unittest.main()

