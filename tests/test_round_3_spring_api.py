import unittest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indexer import _extract_symbols

class TestRound3SpringApi(unittest.TestCase):

    def test_01_get_mapping(self):
        code = """
    @GetMapping("/users")
    public List<User> getUsers() {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "getUsers"), None)
        self.assertIsNotNone(target)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/users")

    def test_02_post_mapping_value(self):
        code = """
    @PostMapping(value="/users")
    public void createUser() {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "createUser"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/users")

    def test_03_request_mapping_path(self):
        code = """
    @RequestMapping(path="/api/v1")
    public class UserController {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "UserController"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/api/v1")

    def test_04_delete_mapping(self):
        code = """
    @DeleteMapping("/users/{id}")
    public void deleteUser(String id) {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "deleteUser"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/users/{id}")

    def test_05_whitespace_tolerance(self):
        code = """
    @GetMapping (  "/spaced"  )
    public void spaced() {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "spaced"), None)
        meta = json.loads(target[7])
        self.assertEqual(meta.get("http_path"), "/spaced")

    def test_06_patch_mapping(self):
        code = """
    @PatchMapping("/users/{id}")
    public void updateUser() {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "updateUser"), None)
        self.assertEqual(json.loads(target[7]).get("http_path"), "/users/{id}")

    def test_07_put_mapping(self):
        code = """
    @PutMapping("/items")
    public void updateItem() {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "updateItem"), None)
        self.assertEqual(json.loads(target[7]).get("http_path"), "/items")

    def test_08_no_annotation(self):
        code = """
    public void internalMethod() {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "internalMethod"), None)
        meta = json.loads(target[7])
        self.assertIsNone(meta.get("http_path"))

    def test_09_class_annotation_persistence(self):
        # Verify that class annotation doesn't bleed into method if method has none
        # Current implementation resets 'last_api_path' after consume.
        # But if class consumes it, method shouldn't get it unless it has its own.
        code = """
    @RequestMapping("/base")
    public class Base {
        public void method() {}
    }
        """
        symbols, _ = _extract_symbols("test.java", code)
        cls = next((s for s in symbols if s[1] == "Base"), None)
        method = next((s for s in symbols if s[1] == "method"), None)
        
        self.assertEqual(json.loads(cls[7]).get("http_path"), "/base")
        self.assertIsNone(json.loads(method[7]).get("http_path"))

    def test_10_multiple_annotations_last_wins(self):
        # If there are multiple lines of annotations, the last one before method should define the path?
        # Or if two @GetMapping exist (invalid java but possible in text), last one wins?
        # Our logic: 'last_api_path' is overwritten until a symbol consumes it.
        code = """
    @GetMapping("/old")
    @GetMapping("/new")
    public void double() {
        """
        symbols, _ = _extract_symbols("test.java", code)
        target = next((s for s in symbols if s[1] == "double"), None)
        self.assertEqual(json.loads(target[7]).get("http_path"), "/new")

if __name__ == '__main__':
    unittest.main()
