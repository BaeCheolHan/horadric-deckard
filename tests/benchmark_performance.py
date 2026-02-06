import os
import time
import json
import shutil
import threading
import sqlite3
from pathlib import Path
from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.core.indexer.main import Indexer
from sari.core.settings import settings
from sari.core.workspace import WorkspaceManager

def test_performance_benchmark():
    # 1. Setup Benchmark Workspace
    test_dir = Path("/tmp/sari_benchmark").resolve() # FORCE RESOLVE
    if test_dir.exists(): shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)
    
    print("\n[Benchmark] Generating 1000 test files...")
    for i in range(1000):
        (test_dir / f"file_{i}.py").write_text(f"def func_{i}():\n    print('Hello {i}')\n" * 10)
    
    # 2. Configure Indexer
    db_path = test_dir / "bench.db"
    db = LocalSearchDB(str(db_path))
    
    norm_path = str(test_dir)
    root_id = WorkspaceManager.root_id(norm_path)
    
    print(f"[Benchmark] Path: {norm_path} | ID: {root_id}")
    
    # Ensure root exists in DB
    db.upsert_root(root_id, norm_path, norm_path, label="bench")
    
    defaults = Config.get_defaults(norm_path)
    defaults["workspace_roots"] = [norm_path]
    cfg = Config(**defaults)
    
    with patch_settings({
        "ENABLE_FTS": "1", 
        "INDEX_L1_BATCH_SIZE": "500",
        "INDEX_WORKERS": "4"
    }):
        indexer = Indexer(cfg, db)
        
        # Start Workers
        for _ in range(4):
            threading.Thread(target=indexer._worker_loop, daemon=True).start()
        
        # 3. Measured Run (Cold Start)
        print(f"[Benchmark] Starting Cold Indexing (1000 files)...")
        start_ts = time.time()
        indexer.scan_once()
        
        while indexer.status.indexed_files < 1000:
            time.sleep(0.1)
            if time.time() - start_ts > 20: break
            
        indexer.storage.writer.flush(timeout=5.0)
        end_ts = time.time()
        print(f"[Benchmark] Cold Indexing Result: {end_ts - start_ts:.2f}s")
        
        # 4. Measured Run (Warm Start - Signature Skip)
        print("[Benchmark] Touching files...")
        for i in range(1000):
            os.utime(test_dir / f"file_{i}.py", None)
            
        print("[Benchmark] Starting Warm Indexing (Signature Skip)...")
        start_ts_warm = time.time()
        indexer.scan_once()
        
        while (indexer.status.indexed_files + indexer.status.skipped_unchanged) < 2000:
            time.sleep(0.1)
            if time.time() - start_ts_warm > 10: break
            
        indexer.storage.writer.flush(timeout=2.0)
        end_ts_warm = time.time()
        print(f"[Benchmark] Warm Indexing Result: {end_ts_warm - start_ts_warm:.2f}s")
        print(f"[Benchmark] Skipped: {indexer.status.skipped_unchanged} files")
        
        # 5. Verify DB
        cur = db._read.cursor()
        cur.execute("SELECT COUNT(*) FROM files")
        count = cur.fetchone()[0]
        print(f"[Benchmark] Final DB File Count: {count}")
        # If still failing FK, we check the files table content
        if count == 0:
            cur.execute("SELECT root_id FROM staging_files LIMIT 1")
            row = cur.fetchone()
            if row: print(f"[Benchmark] Staging Root ID: {row[0]}")
            cur.execute("SELECT root_id FROM roots")
            print(f"[Benchmark] Roots Table: {[r[0] for r in cur.fetchall()]}")

class patch_settings:
    def __init__(self, overrides):
        self.overrides = overrides
    def __enter__(self):
        for k, v in self.overrides.items():
            os.environ[f"SARI__{k}"] = str(v)
            os.environ[f"SARI_{k}"] = str(v)
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        for k in self.overrides:
            os.environ.pop(f"SARI_{k}", None)
            os.environ.pop(f"SARI__{k}", None)

if __name__ == "__main__":
    test_performance_benchmark()
