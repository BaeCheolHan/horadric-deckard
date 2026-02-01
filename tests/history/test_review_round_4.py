
import pytest
from app.db import LocalSearchDB, SearchOptions

class TestReviewRound4:
    """Round 4: Search Quality & Ranking."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "search_test.db"
        db = LocalSearchDB(str(db_path))
        # Insert dummy data
        files = [
            ("src/main.py", "src", 100, 1000, "def main():\n    pass", 0),
            ("src/utils.py", "src", 200, 2000, "def helper():\n    pass", 0),
            ("test/test_main.py", "test", 100, 1000, "def test_main():\n    pass", 0)
        ]
        db.upsert_files(files)
        # Symbols
        symbols = [
            ("src/main.py", "main", "function", 1, 2, "def main():\n    pass", "")
        ]
        db.upsert_symbols(symbols)
        yield db
        db.close()

    def test_search_filename_boost(self, db):
        """Test 1: Exact filename match should rank higher."""
        # Query "main" should match src/main.py and test/test_main.py
        # But src/main.py is exact basename match (or close to it)
        opts = SearchOptions(query="main.py", limit=10)
        results, _ = db.search_v2(opts)
        
        # Expect src/main.py first
        assert len(results) >= 1
        assert results[0].path.endswith("src/main.py")

    def test_search_context_symbol(self, db):
        """Test 2: Search result should include context_symbol if inside a function."""
        # app/db.py uses _get_enclosing_symbol
        # Let's search for "pass" in main.py, it's inside "main" function
        opts = SearchOptions(query="pass", limit=10, file_types=[".py"])
        results, _ = db.search_v2(opts)
        
        main_hit = next((r for r in results if r.path == "src/main.py"), None)
        assert main_hit
        assert main_hit.context_symbol == "function: main"

    def test_search_limit(self, db):
        """Test 3: Verify limit parameter controls output size."""
        # Insert more files
        more_files = [(f"f{i}.py", "repo", 0, 0, "content", 0) for i in range(20)]
        db.upsert_files(more_files)
        
        opts = SearchOptions(query="content", limit=5)
        results, _ = db.search_v2(opts)
        assert len(results) <= 5

    def test_exclude_patterns(self, db):
        """Test 4: Verify exclude patterns work."""
        # "test/test_main.py" should be excluded if we exclude "test/*" via glob?
        # or excluding by path substring? 
        # The DB search uses LIKE or FTS, but exclusions are often filtered post-query or pre-query
        # app/db.py builds SQL with NOT LIKE for exclusions if passed?
        # Actually SearchOptions excludes are applied in SQL usually.
        
        opts = SearchOptions(query="main", exclude_patterns=["test_main.py"])
        results, _ = db.search_v2(opts)
        # Should not find test_main.py
        paths = [r.path for r in results]
        assert "test/test_main.py" not in paths

    def test_ranking_directory_penalty(self, db):
        """Test 5: 'test' or 'mock' in path might have lower rank?"""
        # This depends on if I implemented directory penalty.
        # In `_process_rows`, I added penalties for 'test', 'mock', 'node_modules'.
        
        # Searching "main" matches src/main.py and test/test_main.py
        # src/main.py should be higher score because test/ has penalty (0.5x usually)
        opts = SearchOptions(query="main", limit=10)
        results, _ = db.search_v2(opts)
        
        # Both match "main" in filename.
        # src/main.py -> score 1.0 (base)
        # test/test_main.py -> score * 0.5 (penalty)
        assert results[0].path == "src/main.py"
