import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound4Docstring(unittest.TestCase):

    def test_01_python_module_docstring(self):
        # Module level docstring is tricky with current _extract_symbols as it usually looks for symbols
        # Actually _extract_symbols focuses on symbols (functions/classes).
        # It DOES grab class/func docstrings.
        code = '''
def my_func():
    """This is a docstring."""
    pass
'''
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "my_func"), None)
        self.assertEqual(target[8].strip(), "This is a docstring.")

    def test_02_java_javadoc_class(self):
        code = """
/**
 * User class.
 * Represents a user.
 */
public class User {
}
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "User"), None)
        self.assertIn("User class.", target[8])
        self.assertIn("Represents a user.", target[8])

    def test_03_java_javadoc_method(self):
        code = """
    /**
     * Gets the name.
     */
    public String getName() {
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "getName"), None)
        self.assertIn("Gets the name.", target[8])

    def test_04_java_annotation_interruption(self):
        # Docstring -> Annotation -> Method
        # Should still capture docstring
        code = """
    /**
     * Creates a user.
     */
    @PostMapping("/users")
    public void createUser() {
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "createUser"), None)
        self.assertIn("Creates a user.", target[8])

    def test_05_java_single_line_javadoc(self):
        code = """
    /** Simple doc */
    public void simple() {
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "simple"), None)
        self.assertIn("Simple doc", target[8])

    def test_06_stale_docstring_clearing(self):
        # Docstring -> Non-symbol code -> Symbol
        # Docstring should NOT attach to Symbol
        code = """
    /** Old doc */
    private int x = 1;
    
    public void fresh() {
"""
        # x is not captured as symbol currently (field support is weak/none)
        # But 'fresh' should NOT have 'Old doc'
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "fresh"), None)
        self.assertFalse(target[8], "Docstring should be empty")

    def test_07_multiple_symbols_docstrings(self):
        code = """
    /** Doc A */
    class A {}
    
    /** Doc B */
    class B {}
"""
        symbols, _ = _extract_symbols("test.java", code)
        a = next(s for s in symbols if s[1] == "A")
        b = next(s for s in symbols if s[1] == "B")
        self.assertIn("Doc A", a[8])
        self.assertIn("Doc B", b[8])
        self.assertNotIn("Doc A", b[8])

    def test_08_python_multiline_docstring(self):
        code = '''
class MyClass:
    """
    Line 1
    Line 2
    """
    pass
'''
        symbols, _ = _extract_symbols("test.py", code)
        target = next((s for s in symbols if s[1] == "MyClass"), None)
        self.assertIn("Line 1", target[8])
        self.assertIn("Line 2", target[8])

    def test_09_java_star_stripping(self):
        code = """
    /**
     *  * Bullet point
     */
    public void bullet() {
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "bullet"), None)
        # Should handle stripping correctly
        self.assertIn("* Bullet point", target[8]) 

    def test_10_docstring_and_extends(self):
        code = """
/**
 * Special dog.
 */
public class Dog extends Animal {
"""
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "Dog"), None)
        self.assertIn("Special dog.", target[8])

if __name__ == '__main__':
    unittest.main()