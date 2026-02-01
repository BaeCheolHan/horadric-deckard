
import pytest
import sqlite3
from unittest.mock import MagicMock, patch
from app.db import LocalSearchDB, SearchOptions, SearchHit

class TestReviewRound10:
    """Round 10: Advanced Search & Fallbacks."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "search.db"
        db = LocalSearchDB(str(db_path))
        # Insert some data
        db.upsert_files([("foo.py", "repo", 1, 1, "def foo(): pass", 0)])
        yield db
        db.close()

    def test_regex_search_valid(self, db):
        """Test 1: Valid regex search."""
        opts = SearchOptions(query="def f.*", use_regex=True)
        # Assuming search_v2 is used
        hits, meta = db.search_v2(opts)
        assert len(hits) == 1
        assert hits[0].path == "foo.py"
        assert meta.get("regex_mode") is True

    def test_regex_search_invalid(self, db):
        """Test 2: Invalid regex handles gracefully."""
        opts = SearchOptions(query="[", use_regex=True)
        hits, meta = db.search_v2(opts)
        assert len(hits) == 0
        assert "regex_error" in meta

    def test_fts_failure_fallback(self, db):
        """Test 3: FTS failure triggers LIKE fallback."""
        # Mock _search_fts to return None (indicating failure) OR raise Exception?
        # Code: 
        # try: ... except OperationalError: return None
        # So check logic: if _search_fts returns None, it calls _search_like.
        
        with patch.object(db, '_search_fts', side_effect=sqlite3.OperationalError("Mock FTS fail")):
            # Wait, if side_effect raises, the method raises. 
            # The method *catches* exception internally?
            # Let's check source code again?
            # Line 765: except sqlite3.OperationalError: return None # FTS failed
            # But that's inside _search_fts? 
            # No, line 765 is inside _search_fts CATCHING it.
            # So if expected SQL fails, it returns None.
            # But the query has to execute.
            # If I patch `_read.execute` to raise?
            pass

        # Easier way: Patch _search_fts to explicitly return None (simulating internal catch and return)
        with patch.object(db, '_search_fts', return_value=None):
             opts = SearchOptions(query="foo")
             hits, meta = db.search_v2(opts)
             assert meta.get("fallback_used") is True
             assert len(hits) == 1 # Found by LIKE

    def test_unicode_skips_fts(self, db):
        """Test 4: Unicode query skips FTS check (if logic present)."""
        # Logic: has_unicode = any(ord(c) > 127 for c in q) -> if true, skip FTS
        opts = SearchOptions(query="한글")
        
        # We want to ensure _search_fts is NOT called.
        with patch.object(db, '_search_fts') as mock_fts:
            db.search_v2(opts)
            mock_fts.assert_not_called()

    def test_short_query_skips_fts(self, db):
        """Test 5: Short query (<3 chars) skips FTS check."""
        opts = SearchOptions(query="ab")
        
        with patch.object(db, '_search_fts') as mock_fts:
            db.search_v2(opts)
            mock_fts.assert_not_called()
