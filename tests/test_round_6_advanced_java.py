import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound6AdvancedJava(unittest.TestCase):

    def test_01_java_record(self):
        # Java 16+ records are essentially classes
        code = "public record User(String name, int age) {}"
        symbols, _ = _extract_symbols("test.java", code)
        # Current regex expects 'class|interface|enum'. 'record' might be missing.
        target = next((s for s in symbols if s[1] == "User"), None)
        self.assertIsNotNone(target, "Should detect Java records")
        self.assertEqual(target[2], "class") # or record if we support it

    def test_02_sealed_class_permits(self):
        # 'sealed' modifier shouldn't break regex
        code = "public sealed class Shape permits Circle, Square {}"
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "Shape"), None)
        self.assertIsNotNone(target)

    def test_03_wildcard_generics(self):
        code = "class MyList extends ArrayList<? extends Number> {}"
        symbols, relations = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "MyList"), None)
        self.assertIsNotNone(target)
        # Relation check: ArrayList or ArrayList<? ...>
        rel = next((r for r in relations if r[1] == "MyList" and r[4] == "extends"), None)
        self.assertTrue(rel[3].startswith("ArrayList"))

    def test_04_anonymous_class_ignore(self):
        # Anonymous class usually looks like 'new Runnable() { ... }'
        # Regex for class definition shouldn't match 'new Runnable'
        code = """
        public void run() {
            Runnable r = new Runnable() {
                public void run() {}
            };
        }
        """
        symbols, _ = _extract_symbols("test.java", code)
        # Should detect 'run' method, but NOT 'Runnable' as a class definition
        classes = [s for s in symbols if s[2] == "class"]
        self.assertEqual(len(classes), 0)

    def test_05_local_class_inside_method(self):
        code = """
        public void outer() {
            class Local {}
        }
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "Local"), None)
        self.assertIsNotNone(target)

    def test_06_kotlin_data_class(self):
        code = "data class User(val name: String)"
        symbols, _ = _extract_symbols("test.kt", code)
        target = next((s for s in symbols if s[1] == "User"), None)
        self.assertIsNotNone(target)

    def test_07_kotlin_inheritance(self):
        # Kotlin uses ':' for inheritance
        code = "class Dog : Animal()"
        symbols, relations = _extract_symbols("test.kt", code)
        target = next((s for s in symbols if s[1] == "Dog"), None)
        self.assertIsNotNone(target)
        # Relation check
        rel = next((r for r in relations if r[1] == "Dog" and r[4] == "extends"), None)
        self.assertIsNotNone(rel, "Kotlin inheritance ':' should be detected")
        self.assertEqual(rel[3], "Animal")

    def test_08_complex_annotation_value(self):
        # Regex expects string literal. Concatenation might fail to capture path, but shouldn't crash.
        code = '@GetMapping(path = "/api" + "/v1")\npublic void api() {}'
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "api"), None)
        # Current implementation probably won't catch "/api/v1" because regex looks for "..."
        # But verify it parses the method at least.
        self.assertIsNotNone(target)

    def test_09_commented_out_class(self):
        code = "// public class Ignored {}"
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "Ignored"), None)
        self.assertIsNone(target, "Commented class should be ignored")

    def test_10_string_content_class(self):
        code = 'String s = "public class Fake {}";'
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "Fake"), None)
        self.assertIsNone(target, "Class inside string should be ignored")

if __name__ == '__main__':
    unittest.main()
