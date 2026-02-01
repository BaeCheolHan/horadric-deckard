
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.indexer import Indexer
import os

class TestReviewRound6:
    """Round 6: File System Filtering & Indexing Rules."""

    @pytest.fixture
    def indexer(self, tmp_path):
        cfg = MagicMock()
        cfg.workspace_root = str(tmp_path)
        cfg.exclude_dirs = ["node_modules", ".git"]
        cfg.exclude_globs = ["*.min.js", "secret.txt"]
        cfg.include_ext = [".py", ".js"]
        cfg.include_files = ["Dockerfile"]
        cfg.max_file_bytes = 100
        
        db = MagicMock()
        logger = MagicMock()
        idx = Indexer(cfg, db, logger)
        return idx

    def test_exclude_dir_logic(self, indexer):
        """Test 1: node_modules and .git should be skipped."""
        # _iter_files logic hard to test without mocking os.walk or creating real files.
        # Let's create real files in tmp_path.
        root = Path(indexer.cfg.workspace_root)
        
        (root / "node_modules").mkdir()
        (root / "node_modules" / "lib.js").touch()
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").touch()
        (root / "src").mkdir()
        (root / "src" / "main.py").touch()
        
        files = list(indexer._iter_files(root))
        paths = [str(f.relative_to(root)) for f in files]
        
        assert "src/main.py" in paths
        assert "node_modules/lib.js" not in paths
        assert ".git/HEAD" not in paths

    def test_exclude_glob_logic(self, indexer):
        """Test 2: *.min.js and secret.txt should be skipped."""
        root = Path(indexer.cfg.workspace_root)
        
        (root / "app.min.js").touch()
        (root / "secret.txt").touch()
        (root / "ok.js").touch()
        
        files = list(indexer._iter_files(root))
        paths = [str(f.relative_to(root)) for f in files]
        
        assert "ok.js" in paths
        assert "app.min.js" not in paths
        assert "secret.txt" not in paths

    def test_include_file_override(self, indexer):
        """Test 3: 'Dockerfile' should be included even without extension match."""
        root = Path(indexer.cfg.workspace_root)
        (root / "Dockerfile").touch() 
        # Dockerfile has no extension, normally skipped unless exact match in include_files
        
        files = list(indexer._iter_files(root))
        paths = [str(f.relative_to(root)) for f in files]
        
        assert "Dockerfile" in paths

    @patch("pathlib.Path.read_text")
    def test_large_file_skip(self, mock_read, indexer):
        """Test 4: Files larger than max_bytes should remain type='unchanged' or skipped?"""
        # The logic is in _process_file_task.
        # If size > max_lines (actually max bytes logic is inside _process_file_task?)
        # Let's check logic: if st.st_size > cfg.max_file_bytes => return None?
        
        root = Path(indexer.cfg.workspace_root)
        fpath = root / "large.py"
        fpath.touch()
        
        st = os.stat(fpath)
        # Mock huge size
        st = MagicMock()
        st.st_size = 200 # Limit is 100
        st.st_mtime = 100
        
        # We need to call _process_file_task
        # Note: _process_file_task is instance method
        res = indexer._process_file_task(root, fpath, st, 0, 0)
        
        # If too large, it logs and returns None (ignores)
        # Or maybe it indexes as "skipped"? 
        # Code check: if st.st_size > self.cfg.max_file_bytes: log warning, return None
        assert res is None

    @patch("pathlib.Path.read_text")
    def test_read_permission_error(self, mock_read, indexer):
        """Test 5: Read permission error should be handled gracefully."""
        # _process_file_task calls read_text
        root = Path(indexer.cfg.workspace_root)
        fpath = root / "protected.py"
        fpath.touch()
        st = os.stat_result((0,0,0,0,0,0,50,0,0,0)) # small size
        
        mock_read.side_effect = PermissionError("Access denied")
        indexer.db.get_file_meta.return_value = None # Treat as new/changed
        
        # Should return {"type": "unchanged", "rel": ...} logic?
        # v2.5.3 update says: if read failed, mark as unchanged (seen) to prevent deletion.
        res = indexer._process_file_task(root, fpath, st, 0, 0)
        
        assert res is not None
        assert res["type"] == "unchanged"
