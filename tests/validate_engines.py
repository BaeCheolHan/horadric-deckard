import os
import sys
from pathlib import Path
from sari.core.parsers.ast_engine import ASTEngine
from sari.core.parsers.factory import ParserFactory
from sari.core.utils import _normalize_engine_text

# Real-world Samples
PYTHON_SAMPLE = """
class SessionRedirectMixin(object):
    def get_redirect_target(self, resp):
        pass
    def resolve_redirects(self, resp, req):
        pass

class Session(SessionRedirectMixin):
    def __init__(self):
        self.headers = {}
    def request(self, method, url):
        pass
"""

KOREAN_SAMPLE = """
# 네이버 egjs-grid
이 라이브러리는 레이아웃을 효율적으로 배치합니다.
- MasonryGrid: 같은 너비의 아이템을 쌓습니다.
"""

def validate_engines():
    print("\n=== Engine Validation Report ===")
    
    # 1. Tree-sitter (AST) Check
    ast = ASTEngine()
    print(f"Tree-sitter Enabled: {ast.enabled}")
    
    parser = ParserFactory.get_parser(".py")
    symbols, relations = parser.extract("sessions.py", PYTHON_SAMPLE)
    
    print(f"Python Symbols Extracted: {len(symbols)}")
    for s in symbols[:5]:
        print(f" - [{s[2]}] {s[1]} (line {s[5]})")
    
    assert any(s[1] == "Session" for s in symbols)
    assert any(s[1] == "request" for s in symbols)
    
    # 2. CJK Tokenizer Check
    normalized = _normalize_engine_text(KOREAN_SAMPLE)
    print(f"CJK Normalization: {len(normalized)} chars")
    assert "네이버" in normalized
    assert "레이아웃" in normalized
    print("CJK Validation: PASSED")

    # 3. Systematic Overlap Fix Check
    from sari.core.indexer.scanner import Scanner
    from unittest.mock import MagicMock
    
    temp_dir = Path("/tmp/sari_overlap_test")
    if temp_dir.exists(): 
        import shutil
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    (temp_dir / "file1.txt").write_text("parent")
    
    child = temp_dir / "child"
    child.mkdir()
    (child / ".sari").mkdir() 
    (child / "file2.txt").write_text("child")
    
    cfg = MagicMock()
    cfg.exclude_dirs = []
    from sari.core.settings import settings as global_settings
    cfg.settings = global_settings
    
    scanner = Scanner(cfg)
    entries = list(scanner.iter_file_entries(temp_dir))
    paths = [str(p.relative_to(temp_dir)) for p, st, ex in entries]
    print(f"Scanned Paths: {paths}")
    
    assert "file1.txt" in paths
    assert "child/file2.txt" not in paths
    print("Systematic Overlap Fix: PASSED")

if __name__ == "__main__":
    validate_engines()
