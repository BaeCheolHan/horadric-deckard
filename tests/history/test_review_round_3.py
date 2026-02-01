
import pytest
import sqlite3
import os
from app.db import LocalSearchDB

class TestReviewRound3:
    """Round 3: Database Schema & Migration Logic."""
    
    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = LocalSearchDB(str(db_path))
        yield db
        db.close()

    def test_upsert_and_retrieval(self, db):
        """Test 1: Upsert symbols with new end_line field and retrieve them."""
        # path, name, kind, line, end_line, content, parent_name
        symbols = [
            ("main.py", "MyClass", "class", 10, 20, "class MyClass:...", ""),
            ("main.py", "method", "method", 12, 15, "  def method(self):...", "MyClass")
        ]
        
        # Must upsert file first due to FK
        db.upsert_files([("main.py", "repo", 0, 0, "full content", 0)])
        
        count = db.upsert_symbols(symbols)
        assert count == 2
        
        # Check get_symbol_block
        block = db.get_symbol_block("main.py", "MyClass")
        assert block
        assert block["start_line"] == 10
        assert block["end_line"] == 20

    def test_get_symbol_block_fallback(self, db):
        """Test 2: If end_line is 0 (legacy), fallback to reasonable default."""
        db.upsert_files([("legacy.py", "repo", 0, 0, "L1\nL2\nL3\nL4\nL5\nL6\nL7\nL8\nL9\nL10\nL11\nL12", 0)])
        
        # Directly insert legacy-style symbol (end_line=0 due to default)
        with db._lock:
            db._write.execute(
                "INSERT INTO symbols(path, name, kind, line, content, end_line) VALUES (?,?,?,?,?,?)",
                ("legacy.py", "LegacyFunc", "function", 1, "def LegacyFunc():", 0)
            )
            db._write.commit()
            
        block = db.get_symbol_block("legacy.py", "LegacyFunc")
        assert block
        # Fallback logic: line_start + 10
        assert block["end_line"] == 11
        assert len(block["content"].splitlines()) <= 11

    def test_search_symbols_ranking(self, db):
        """Test 3: Search symbols should rank exact matches or shorter matches higher."""
        db.upsert_files([("a.py", "r", 0,0,"",0)])
        symbols = [
            ("a.py", "User", "class", 1, 10, "", ""),
            ("a.py", "UserFactory", "class", 20, 30, "", ""),
            ("a.py", "AbstractUser", "class", 40, 50, "", "")
        ]
        db.upsert_symbols(symbols)
        
        hits = db.search_symbols("User")
        assert len(hits) >= 3
        # First hit should be "User" (shortest, exact match preference by length sort)
        assert hits[0]["name"] == "User"

    def test_search_symbols_empty(self, db):
        """Test 4: Searching with empty query should return empty."""
        assert db.search_symbols("") == []
        assert db.search_symbols("   ") == []

    def test_read_file_from_db(self, db):
        """Test 5: read_file basic functionality."""
        content = "Hello World"
        db.upsert_files([("test.txt", "repo", 0, 0, content, 0)])
        
        res = db.read_file("test.txt")
        assert res == content
        
        assert db.read_file("non_existent.txt") is None
