import os
import shutil
import time
import pytest
from pathlib import Path
from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.core.indexer.main import Indexer
from sari.core.workspace import WorkspaceManager
from sari.core.settings import settings

def test_core_business_logic_smoke():
    """
    End-to-end smoke test for the core business logic:
    Scanner -> Indexer -> DB -> Search -> Read.
    """
    # 1. Setup
    test_root = Path("/tmp/sari_smoke_test").resolve()
    if test_root.exists(): shutil.rmtree(test_root)
    test_root.mkdir(parents=True)
    
    # Create sample files
    (test_root / "main.py").write_text("def hello():\n    pass")
    (test_root / "utils.js").write_text("function add(a, b) { return a + b; }")
    (test_root / "subdir").mkdir()
    (test_root / "subdir" / "data.txt").write_text("some secret data")
    
    # 2. Initialize DB & Config
    db_path = test_root / "sari.db"
    db = LocalSearchDB(str(db_path))
    
    root_id = WorkspaceManager.root_id(str(test_root))
    db.upsert_root(root_id, str(test_root), str(test_root), label="smoke")
    
    defaults = Config.get_defaults(str(test_root))
    defaults["include_ext"].append(".txt")
    cfg = Config(**defaults)
    
    # 3. Execution: Indexing
    indexer = Indexer(cfg, db)
    indexer.scan_once()
    
    # Manual worker trigger
    while True:
        item = indexer.coordinator.get_next_task()
        if not item: break
        rid, task = item
        indexer._handle_task(rid, task)
    
    # Flush
    indexer.storage.writer.flush(timeout=5.0)
    indexer._trigger_staging_merge()
    indexer.storage.writer.flush(timeout=5.0)
    
    # 4. Verification: DB Content
    cur = db._read.cursor()
    cur.execute("SELECT COUNT(*) FROM files")
    count = cur.fetchone()[0]
    print(f"[SmokeTest] File Count: {count}")
    if count == 0:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        print(f"[SmokeTest] Tables: {[r[0] for r in cur.fetchall()]}")
    assert count == 3
    
    # 5. Verification: Symbol Extraction
    cur.execute("SELECT name, kind FROM symbols WHERE name = 'hello'")
    sym = cur.fetchone()
    assert sym is not None
    
    # 6. Verification: Search Logic
    files = db.search_files("main")
    assert len(files) >= 1
    
    # 7. Verification: Read Logic
    content = db.read_file(f"{root_id}/main.py")
    assert "def hello" in content
    
    # 8. Cleanup
    db.close_all()
    if test_root.exists(): shutil.rmtree(test_root)

if __name__ == "__main__":
    test_core_business_logic_smoke()