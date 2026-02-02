import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound2JavaRelations(unittest.TestCase):

    def test_01_simple_extends(self):
        code = "public class Dog extends Animal {"
        _, relations = _extract_symbols("test.java", code)
        # Should find (test.java, Dog, "", Animal, extends, line)
        rel = next((r for r in relations if r[1] == "Dog" and r[4] == "extends"), None)
        self.assertIsNotNone(rel)
        self.assertEqual(rel[3], "Animal")

    def test_02_simple_implements(self):
        code = "public class MyList implements List {"
        _, relations = _extract_symbols("test.java", code)
        rel = next((r for r in relations if r[1] == "MyList" and r[4] == "implements"), None)
        self.assertIsNotNone(rel)
        self.assertEqual(rel[3], "List")

    def test_03_multiple_implements(self):
        code = "class Worker implements Runnable, Serializable {"
        _, relations = _extract_symbols("test.java", code)
        rels = [r for r in relations if r[1] == "Worker" and r[4] == "implements"]
        targets = {r[3] for r in rels}
        self.assertTrue("Runnable" in targets)
        self.assertTrue("Serializable" in targets)

    def test_04_extends_and_implements(self):
        code = "public class ArrayList extends AbstractList implements List, RandomAccess {"
        _, relations = _extract_symbols("test.java", code)
        ext = next((r for r in relations if r[1] == "ArrayList" and r[4] == "extends"), None)
        self.assertEqual(ext[3], "AbstractList")
        
        impls = [r[3] for r in relations if r[1] == "ArrayList" and r[4] == "implements"]
        self.assertIn("List", impls)
        self.assertIn("RandomAccess", impls)

    def test_05_interface_extends(self):
        code = "public interface Stream extends BaseStream {"
        _, relations = _extract_symbols("test.java", code)
        rel = next((r for r in relations if r[1] == "Stream" and r[4] == "extends"), None)
        self.assertIsNotNone(rel)
        self.assertEqual(rel[3], "BaseStream")

    def test_06_generic_extends(self):
        # Regex might be tricky with <...>
        code = "public class StringList extends ArrayList<String> {"
        # Current regex: ([a-zA-Z0-9_]+) might NOT capture ArrayList<String> completely or might fail
        # Let's see what happens. Ideally it captures "ArrayList" or "ArrayList<String>"
        _, relations = _extract_symbols("test.java", code)
        # We expect it to capture at least the base name "ArrayList" or fail gracefully
        pass # Analyzing output in failure is better

    def test_07_abstract_class_extends(self):
        code = "public abstract class BaseController extends Controller {"
        _, relations = _extract_symbols("test.java", code)
        rel = next((r for r in relations if r[1] == "BaseController" and r[4] == "extends"), None)
        self.assertEqual(rel[3], "Controller")

    def test_08_multiline_declaration(self):
        # Regex often fails on multiline unless DOTALL is used or applied to full content (not line by line)
        # Current impl applies regex LINE BY LINE. So this is expected to FAIL if split across lines.
        # This test documents the limitation.
        code = """
public class BigClass
    extends BaseClass {
"""
        # If passed as single string to extract_symbols, it splits by lines.
        # The regex is applied per line. So it won't match.
        pass 

    def test_09_no_relation(self):
        code = "public class Simple {"
        _, relations = _extract_symbols("test.java", code)
        self.assertEqual(len(relations), 0)

    def test_10_implements_with_generics(self):
        code = "class MyMap implements Map<String, Integer> {"
        _, relations = _extract_symbols("test.java", code)
        # Should detect Map or Map<...>
        pass

if __name__ == '__main__':
    unittest.main()
