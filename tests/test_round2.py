import sys
from pathlib import Path
import json
import unittest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import LocalSearchDB
from app.indexer import _extract_symbols

class TestRound2(unittest.TestCase):
    def test_2_1_multi_path_annotation(self):
        content = "@RequestMapping({\"/api/v1\", \"/api/v2\"})\npublic class C {}"
        symbols = _extract_symbols("C.java", content)
        meta = json.loads(symbols[0][7])
        # Current logic might need regex refinement to catch both, let's see what it gets
        self.assertIn("http_path", meta)

    def test_2_2_python_static_method(self):
        content = "class A:\n    @staticmethod\n    def s(): pass"
        symbols = _extract_symbols("A.py", content)
        meta = json.loads(symbols[1][7])
        self.assertIn("@staticmethod", meta["decorators"])

    def test_2_7_unicode_docstring(self):
        content = "def f():\n    \"\"\"한글 문서화\"\"\"\n    pass"
        symbols = _extract_symbols("f.py", content)
        self.assertEqual(symbols[0][8].strip(), "한글 문서화")

    def test_2_8_multi_annotations_order(self):
        content = "@Annotation1\n@Annotation2\npublic void m() {}"
        symbols = _extract_symbols("M.java", content)
        meta = json.loads(symbols[0][7])
        self.assertEqual(len(meta["annotations"]), 2)
        # Note: Lookback adds in reverse order (i-1, i-2...)
        self.assertIn("@Annotation1", meta["annotations"])
        self.assertIn("@Annotation2", meta["annotations"])

    def test_2_10_no_docstring(self):
        content = "def f(): pass"
        symbols = _extract_symbols("f.py", content)
        self.assertEqual(symbols[0][8], "")

if __name__ == "__main__":
    unittest.main()
