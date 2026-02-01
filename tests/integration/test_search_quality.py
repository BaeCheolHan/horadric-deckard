
import pytest
import sqlite3
import time
from pathlib import Path
from app.db import LocalSearchDB, SearchOptions

class TestSearchQuality:
    """
    Phase 2: Shield 3 (Search Quality) Tests.
    Verifies Hybrid Search strategies and Definition Ranking.
    """

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = LocalSearchDB(db_path)
        yield db
        db.close()

    def test_definition_ranking(self, db):
        """Test that definitions rank higher than references."""
        # Insert Data directly
        # file1: Definition
        db.upsert_files([(
            "src/models.py", 
            "my_repo", 
            int(time.time()), 
            100, 
            "class User:\n    pass",
            int(time.time())
        )])
        # file2: Reference
        db.upsert_files([(
            "src/main.py", 
            "my_repo", 
            int(time.time()), 
            100, 
            "from models import User\nu = User()",
            int(time.time())
        )])
        
        # Insert Symbol for file1
        db.upsert_symbols([(
            "src/models.py",
            "User",
            "class",
            1,
            2,
            "class User:\n    pass",
            ""
        )])
        
        # Search
        opts = SearchOptions(query="User", limit=10)
        hits, meta = db.search_v2(opts)
        
        assert len(hits) >= 2
        
        # Expect file1 (Definition) to be first
        assert hits[0].path == "src/models.py"
        assert hits[0].score > hits[1].score
        assert "Symbol: class User" in hits[0].hit_reason


    def test_hybrid_merge(self, db):
        """Test merging of Symbol and FTS hits."""
        now = int(time.time())
        # Insert files needed for this test
        db.upsert_files([(
            "src/models.py", 
            "my_repo", 
            now, 100, "class User:\n    pass", now
        )])
        db.upsert_files([(
            "src/main.py", 
            "my_repo", 
            now, 100, "from models import User\nu = User()", now
        )])
        db.upsert_symbols([(
            "src/models.py", "User", "class", 1, 2, "class User:\n    pass", ""
        )])

        # File only in FTS (no symbol)
        db.upsert_files([(
            "README.md", 
            "docs", 
            now, 
            100, 
            "About the User class...",
            now
        )])
        
        opts = SearchOptions(query="User", limit=10)
        hits, meta = db.search_v2(opts)
        
        # Should find models.py (Symbol), main.py (Reference), README.md (FTS)
        paths = {h.path for h in hits}
        assert "src/models.py" in paths
        assert "src/main.py" in paths
        assert "README.md" in paths
        
    def test_pagination_with_merge(self, db):
        """Test pagination works despite merging."""
        now = int(time.time())
        
        # Create 10 separate files, each with a match
        files = []
        symbols = []
        
        for i in range(10):
            files.append((f"def{i}.py", "repo", now, 10, f"def Foo{i}(): pass", now))
            symbols.append((f"def{i}.py", f"Foo{i}", "function", 1, 1, f"def Foo{i}(): pass", ""))
            
        db.upsert_files(files)
        db.upsert_symbols(symbols)
        
        # Search "def" to match all files content
        opts = SearchOptions(query="def", limit=5, offset=0)
        hits1, meta1 = db.search_v2(opts)
        assert len(hits1) == 5

        
        opts = SearchOptions(query="def", limit=5, offset=5)
        hits2, meta2 = db.search_v2(opts)
        assert len(hits2) == 5
        
        # Verify hits are unique files
        paths1 = {h.path for h in hits1}
        paths2 = {h.path for h in hits2}
        assert len(paths1) == 5
        assert len(paths2) == 5
        assert not (paths1 & paths2) # No overlap


