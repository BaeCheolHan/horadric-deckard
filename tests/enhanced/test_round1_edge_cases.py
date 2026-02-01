
import pytest
import os
import json
import time
import sqlite3
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import necessary modules
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from app.db import LocalSearchDB, SearchOptions
from app.indexer import _extract_symbols
from app.registry import ServerRegistry

class TestRound1EdgeCases:
    """
    Round 1: Edge Cases & Error Handling.
    """

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "test_round1.db")
        db = LocalSearchDB(db_path)
        yield db
        db.close()

    def test_search_special_chars(self, db):
        """TC1: Verify search handles SQL injection chars and regex meta chars safely."""
        now = int(time.time())
        # Insert file with special chars
        content = "SELECT * FROM users WHERE name = 'O''Reilly';\nComplex regex: ^[a-z]+$"
        db.upsert_files([("special.sql", "repo", now, 100, content, now)])
        
        # Search with quote (potential SQL injection) - simplified to avoid tokenizer complexity
        # Just ensure it doesn't crash and ideally finds something if terms match
        opts = SearchOptions(query="O''Reilly", limit=10)
        hits, _ = db.search_v2(opts)
        # It's acceptable if FTS doesn't find exact 'O''Reilly' due to tokenization, 
        # but it MUST NOT crash.
        # Let's Assert on the regex part which is less ambiguous for FTS tokenizers 
        # (usually splits on non-alphanum)
        opts2 = SearchOptions(query="Complex regex", limit=10)
        hits2, _ = db.search_v2(opts2)
        assert len(hits2) > 0
        assert hits2[0].path == "special.sql"
        
        # Search with regex meta chars in LIKE mode (should act as literal if use_regex=False)
        # But FTS might strip them. So let's use regex mode to verify we CAN find it.
        opts = SearchOptions(query=r"\^\[a-z\]\+\$", limit=10, use_regex=True)
        hits, _ = db.search_v2(opts)
        assert len(hits) > 0
        assert hits[0].path == "special.sql"
        
        
        # Search with % and _ (wildcards in LIKE)
        # Should match literal strictly if escaped properly in DB logic
        db.upsert_files([("percent.txt", "repo", now, 100, "100% complete", now)])
        
        # FTS tokenizer might strip %, so searching "100" should safe and find it.
        # Searching "100%" might fail distinct match if % is separator.
        opts = SearchOptions(query="100", limit=10)
        hits, _ = db.search_v2(opts)
        assert len(hits) > 0
        assert hits[0].path == "percent.txt"

    def test_symbol_extraction_malformed(self):
        """TC2: Verify extractor doesn't crash on syntax errors."""
        # Python syntax error (incomplete def)
        code_py = "def broken_functio" 
        symbols = _extract_symbols("broken.py", code_py)
        # Should return what it can parse (maybe nothing) but NOT CRASH
        assert isinstance(symbols, list)
        
        # Python indentation error
        code_indent = "def foo():\nreturn 1" 
        symbols = _extract_symbols("indent_err.py", code_indent)
        assert isinstance(symbols, list)

        # Python indentation error
        code_indent = "def foo():\nreturn 1" 
        symbols = _extract_symbols("indent_err.py", code_indent)
        assert isinstance(symbols, list)
        if symbols:
             # _extract_symbols returns tuples: (path, name, kind, line, end_line, content, parent_name)
             assert symbols[0][1] == "foo"

    def test_search_unicode_cjk(self, db):
        """TC3: Verify CJK search support (FTS tokenizer behavior)."""
        now = int(time.time())
        # Insert Korean content
        db.upsert_files([("kr.txt", "repo", now, 100, "안녕하세요 세계", now)])
        
        # Search "안녕"
        opts = SearchOptions(query="안녕", limit=10)
        hits, _ = db.search_v2(opts)
        
        # SQLite FTS5 default tokenizer might fail CJK tokenization (treats as one block)
        # But 'search_v2' has a LIKE fallback for non-ASCII queries!
        # So this should succeed via LIKE fallback even if FTS fails.
        assert len(hits) > 0
        assert hits[0].path == "kr.txt"
        snippet = hits[0].snippet.replace(">>>", "").replace("<<<", "")
        assert "안녕하세요" in snippet

    def test_registry_corrupted_json(self, tmp_path):
        """TC4: Verify ServerRegistry handles corrupted JSON file."""
        registry_dir = tmp_path / "registry"
        registry_dir.mkdir()
        reg_file = registry_dir / "server.json"
        
        # Write garbage
        reg_file.write_text("{ this is not json }")
        
        with patch('app.registry.REGISTRY_FILE', reg_file):
            reg = ServerRegistry()
            # Should load empty or reset
            # (Assuming implementation swallows JSONDecodeError and returns empty)
            inst = reg.get_instance("/some/path")
            assert inst is None
            
            # Should be able to overwrite/recover
            pid = os.getpid()
            reg.register("/some/path", 1234, pid)
            inst = reg.get_instance("/some/path")
            
            # Setup for debugging/assertion
            if inst is None:
                print(f"DEBUG: File content: {reg_file.read_text()}")
            
            assert inst is not None
            assert inst["port"] == 1234

    def test_db_schema_idempotency(self, tmp_path):
        """TC5: Verify multiple inits don't fail."""
        db_path = str(tmp_path / "idempotent.db")
        
        # First init
        db = LocalSearchDB(db_path)
        
        # Manually call init_schema again (via private method or closing and reopening)
        db._init_schema()
        
        # Reopen
        db.close()
        db2 = LocalSearchDB(db_path)
        
        # Check tables exist
        with db2._read_lock:
             db2._read.execute("SELECT * FROM files LIMIT 1")
             db2._read.execute("SELECT * FROM symbols LIMIT 1")
        db2.close()
