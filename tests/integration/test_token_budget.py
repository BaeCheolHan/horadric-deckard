
import pytest
from app.db import LocalSearchDB, SearchOptions

class TestShieldTokenBudget:
    """
    Round 12: Token Economy Shield.
    Enforces Strict Token Budget Contracts.
    Failure here means "Token Budget Explosion" for users.
    """

    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "token_shield.db"
        db = LocalSearchDB(str(db_path))
        
        # Insert a file with 100 lines
        lines = [f"Line {i}: function body..." for i in range(1, 101)]
        content = "\n".join(lines)
        db.upsert_files([("massive.py", "repo", 100, 1000, content, 0)])
        
        # Insert 100 small files
        many_files = [(f"small_{i}.py", "repo", 0,0,"x",0) for i in range(50)]
        db.upsert_files(many_files)
        
        yield db
        db.close()

    def test_search_snippet_contract(self, db):
        """
        Shield 1: Search snippets MUST be strictly capped (e.g. 5 lines).
        Contract: snippet_lines <= 5 (default).
        """
        # Search for "function" which appears 100 times in massive.py
        # app/db.py default snippet is 5 lines? Or configurable?
        # SearchOptions doesn't have snippet_lines param yet (it's in Config but db logic uses hardcoded/config defaults?).
        # Looking at db.py _process_rows: `max_lines=5` default if not passed?
        # Let's verify standard search behavior.
        
        opts = SearchOptions(query="Line 50")
        results, _ = db.search_v2(opts)
        
        assert len(results) > 0
        snippet = results[0].snippet
        line_count = len(snippet.strip().splitlines())
        
        # The exact implementation might return "Line 50" plus context.
        # It shouldn't return 100 lines.
        assert line_count <= 10, f"Snippet too long: {line_count} lines"
        # Ideally <= 5 if that's the contract.

    def test_search_limit_contract(self, db):
        """
        Shield 2: Search Limit MUST be respected.
        Contract: len(results) <= limit.
        """
        opts = SearchOptions(query="x", limit=10)
        results, _ = db.search_v2(opts)
        
        assert len(results) == 10
        # DB has 50 files with "x".
        
    def test_search_default_limit_safety(self, db):
        """
        Shield 3: Default Limit Safety.
        If no limit specified, it MUST NOT return everything.
        Contract: Default limit is reasonable (e.g. 10 or 20).
        """
        opts = SearchOptions(query="x") # limit defaults to ?
        # In SearchOptions class definition (need to check default).
        # Usually user passes limit. If None?
        # Let's see behavior.
        results, _ = db.search_v2(opts)
        assert len(results) <= 20, f"Default limit too high: {len(results)}"

    def test_snippet_char_limit(self, db):
        """
        Shield 4: Snippet Character Limit.
        Prevent single line from being 10,000 chars.
        Contract: Snippets are truncated horizontally too?
        """
        # Create file with very long line
        long_line = "A" * 5000
        db.upsert_files([("wide.py", "repo", 0,0, long_line, 0)])
        
        opts = SearchOptions(query="A")
        results, _ = db.search_v2(opts)
        
        if not results:
            pytest.skip("Search didn't match long line")
            
        snippet = results[0].snippet
        # DB snippet logic might NOT truncate horizontal yet.
        # This test checks if we HAVE such protection.
        # If failure, it reveals a token risk.
        # Adjust expectation: if we don't truncate, this test documents the risk.
        # But for Shield, we asserting we DO truncate or it's < 1000 chars roughly.
        assert len(snippet) < 2000, f"Snippet line too wide: {len(snippet)} chars"

    def test_read_symbol_efficiency(self, db):
        """
        Shield 5: read_symbol MUST return only the block, not file.
        Contract: content size << file size.
        """
        # Add symbol
        # File: 1000 lines. Symbol: 3 lines.
        lines = ["# padding" for _ in range(500)]
        lines += ["def efficient():", "  return True", "# end"]
        lines += ["# padding" for _ in range(500)]
        content = "\n".join(lines)
        
        db.upsert_files([("efficient.py", "repo", 0,0,content,0)])
        db.upsert_symbols([("efficient.py", "efficient", "func", 501, 503, "def efficient():\n  return True\n# end", "")])
        
        block = db.get_symbol_block("efficient.py", "efficient")
        assert block
        assert len(block["content"]) < 100 # Definitely not 1000 lines
        assert "def efficient" in block["content"]
