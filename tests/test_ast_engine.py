import pytest

from sari.core.parsers.ast_engine import ASTEngine


def _has_python_ts():
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_python  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_python_ts(), reason="tree-sitter python runtime not installed")
def test_ast_engine_parses_python_with_current_treesitter_api():
    engine = ASTEngine()
    tree = engine.parse("python", "def hello():\n    return 1\n")
    assert tree is not None


@pytest.mark.skipif(not _has_python_ts(), reason="tree-sitter python runtime not installed")
def test_ast_engine_extracts_python_symbols():
    engine = ASTEngine()
    symbols = engine.extract_symbols("root-x/main.py", "python", "class A:\n    def m(self):\n        pass\n")
    names = [s[1] for s in symbols]
    assert "A" in names
    assert "m" in names

