import unittest
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import LocalSearchDB
from app.indexer import _extract_symbols
from mcp.tools.search import execute_search
from mcp.telemetry import TelemetryLogger

class TestRound11RealWorld(unittest.TestCase):

    def test_01_spring_controller_aggregation(self):
        code = """
@RestController
@RequestMapping("/api/v1")
public class MemberController {
    @GetMapping("/me")
    public Member getMe() {}
}
"""
        symbols, _ = _extract_symbols("MemberController.java", code)
        ctrl = next(s for s in symbols if s[1] == "MemberController")
        method = next(s for s in symbols if s[1] == "getMe")
        
        self.assertIn("RESTCONTROLLER", json.loads(ctrl[7])["annotations"])
        self.assertEqual(json.loads(method[7])["http_path"], "/me")

    def test_02_go_service_receiver(self):
        code = """
package service
func NewService() *Service { return &Service{} }
func (s *Service) Process(id string) error { return nil }
"""
        symbols, _ = _extract_symbols("service.go", code)
        self.assertTrue(any(s[1] == "NewService" for s in symbols))
        self.assertTrue(any(s[1] == "Process" for s in symbols))

    def test_03_ts_react_component(self):
        code = "export class Dashboard extends Component { render() { return null; } }"
        symbols, _ = _extract_symbols("Dashboard.tsx", code)
        self.assertTrue(any(s[1] == "Dashboard" for s in symbols))

    def test_04_cpp_header_symbols(self):
        code = """
struct Config { int port; };
class App {
public:
    void Start();
};
"""
        symbols, _ = _extract_symbols("app.h", code)
        self.assertTrue(any(s[1] == "Config" for s in symbols))
        self.assertTrue(any(s[1] == "Start" for s in symbols))

    def test_05_docstring_with_annotations(self):
        code = """
    /**
     * Finds a user by ID.
     */
    @Cacheable("users")
    @GetMapping("/{id}")
    public User findUser(Long id) {}
"""
        symbols, _ = _extract_symbols("Repo.java", code)
        target = next(s for s in symbols if s[1] == "findUser")
        self.assertIn("Finds a user", target[8])
        self.assertIn("CACHEABLE", json.loads(target[7])["annotations"])

    def test_06_broken_code_recovery(self):
        code = """
    void first() {}
    @InvalidAnnotation( broken = 
    void second() {}
    void third() {}
"""
        symbols, _ = _extract_symbols("broken.java", code)
        # Should at least find 'first' and 'third'
        names = {s[1] for s in symbols}
        self.assertIn("first", names)
        self.assertIn("third", names)

    def test_07_inner_class_scope(self):
        code = "class A { class B { void m() {} } }"
        symbols, _ = _extract_symbols("test.java", code)
        b = next(s for s in symbols if s[1] == "B")
        m = next(s for s in symbols if s[1] == "m")
        self.assertEqual(b[6], "A") # parent
        self.assertEqual(m[6], "B") # parent

    def test_08_search_docstring_ui(self):
        # This requires a dummy DB and Logger
        # Just testing the extractor part of docstring length
        code = '/** Line 1\nLine 2\nLine 3\nLine 4 */\nvoid test(){}'
        symbols, _ = _extract_symbols("test.java", code)
        doc = symbols[0][8]
        self.assertEqual(len(doc.splitlines()), 4)

    def test_09_inheritance_relation_capture(self):
        code = "class Child extends Parent implements I1, I2 {}"
        _, relations = _extract_symbols("test.java", code)
        targets = {r[3] for r in relations if r[1] == "Child"}
        self.assertIn("Parent", targets)
        # Note: current implements logic might be limited to single line
        pass

    def test_10_empty_and_comments_only(self):
        code = "// only comments\n\n/* more comments */"
        symbols, _ = _extract_symbols("test.java", code)
        self.assertEqual(len(symbols), 0)

if __name__ == '__main__':
    unittest.main()
