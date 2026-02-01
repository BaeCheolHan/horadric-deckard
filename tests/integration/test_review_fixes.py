import os
import sqlite3
import pytest
from app.db import LocalSearchDB, SearchOptions
from mcp.tools.search_symbols import execute_search_symbols

@pytest.fixture
def db(tmp_path):
    db_file = str(tmp_path / "test.db")
    db = LocalSearchDB(db_file)
    yield db
    db.close()

def test_search_symbols_limit_fix(db):
    """P1: Verify search_symbols correctly applies limit."""
    # Setup: Add multiple symbols
    db.upsert_files([
        ("main.py", "repo1", 100, 1000, "def foo(): pass\ndef bar(): pass", 1000)
    ])
    db.upsert_symbols([
        ("main.py", "foo", "function", 1, 1, "def foo(): pass", None),
        ("main.py", "bar", "function", 2, 2, "def bar(): pass", None),
        ("main.py", "baz", "function", 3, 3, "def baz(): pass", None),
    ])
    
    # Execute tool with limit=2
    args = {"query": "ba", "limit": 2}
    result = execute_search_symbols(args, db)
    
    text = result["content"][0]["text"]
    assert "Found 2 symbols" in text
    assert "baz" in text or "bar" in text
    assert "- [function] foo" not in text # Should be cut off if sorted (though order isn't guaranteed, 2 is less than 3)

def test_fts_fallback_logic(db):
    """P1: Verify FTS fallback to LIKE."""
    db.upsert_files([
        ("doc.txt", "repo1", 100, 100, "This is a secret keyword purely for testing.", 1000)
    ])
    
    # 1. Unicode query (should bypass FTS and use LIKE)
    # The emoji at the end shouldn't prevent matching "secret" if we search correctly,
    # but here we just want to ensure it DOES find the doc even when FTS is skipped.
    opts = SearchOptions(query="secret", limit=10)
    # Force unicode by adding a char to opts.query inside db call? 
    # Actually, let's just use a query that HAS unicode but the part we match is fine.
    # Wait, the LIKE search uses %query%.
    opts_uni = SearchOptions(query="secret", limit=10)
    # We can't easily force has_unicode without changing the query text.
    # Let's use search_v2 with a query like "secret" and see fts_success.
    
    # Actually, a better way to test "bypass FTS" is to check if 'fallback_used' is in meta.
    # But has_unicode check is in search_v2.
    
    # REVISED TEST 1: Query with unicode that is actually in doc
    db.upsert_files([
        ("uni.txt", "repo1", 100, 100, "Hello 😊 world", 1000)
    ])
    opts_u = SearchOptions(query="😊", limit=10)
    hits, meta = db.search_v2(opts_u)
    assert len(hits) == 1
    assert meta.get("fallback_used") == True
    
    # 2. Force FTS error by dropping fts table (internal simulation)
    if db.fts_enabled:
        with db._lock:
            # We must be careful not to break the DB for other tests if they share it, 
            # but here it's a fresh fixture.
            db._write.execute("DROP TABLE files_fts")
            db._write.commit()
    
    # This search should now fail in FTS (since table is gone) but succeed via LIKE fallback
    opts_fail = SearchOptions(query="secret", limit=10)
    hits, meta = db.search_v2(opts_fail)
    assert len(hits) >= 1
    assert meta.get("fallback_used") == True

def test_stale_symbol_removal(db):
    """P1: Verify symbols are removed when file is updated via upsert_files."""
    path = "service.py"
    # Initial: 1 symbol
    db.upsert_files([(path, "repo1", 100, 100, "def old(): pass", 1000)])
    db.upsert_symbols([(path, "old", "function", 1, 1, "def old(): pass", None)])
    
    assert len(db.search_symbols("old")) == 1
    
    # Update file: 0 symbols (simulating indexer found nothing)
    # The fix is that upsert_files now clears symbols for that path.
    db.upsert_files([(path, "repo1", 101, 120, "new content without symbols", 1001)])
    
    # Symbol should be gone even if upsert_symbols was NEVER called for the new version
    assert len(db.search_symbols("old")) == 0
    
    # Re-add another symbol to ensure it works
    db.upsert_symbols([(path, "new_func", "function", 1, 1, "def new_func(): pass", None)])
    assert len(db.search_symbols("new_func")) == 1
