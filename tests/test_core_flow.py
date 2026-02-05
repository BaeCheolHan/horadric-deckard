import pytest
import time
from sari.core.config.main import Config
from sari.core.indexer.main import Indexer
from sari.core.search_engine import SearchEngine
from sari.core.models import SearchOptions
from sari.core.workspace import WorkspaceManager

def test_full_indexing_and_search_flow(db, temp_workspace, monkeypatch, mock_env):
    """
    Integration Test: Config -> Indexer -> Search
    Verifies that files in the workspace are correctly indexed and searchable.
    """
    # 1. Setup Configuration
    # Force FTS enable via environment variable (Standard way)
    monkeypatch.setenv("SARI_ENABLE_FTS", "1")
    
    ws_path = str(temp_workspace.resolve())
    cfg = Config.load(None, workspace_root_override=ws_path)
    
    # Ensure .py is included for test (ConfigManager might not auto-detect in temp env)
    from dataclasses import replace
    if ".py" not in cfg.include_ext:
        new_ext = list(cfg.include_ext) + [".py"]
        cfg = replace(cfg, include_ext=new_ext)
    
    # 3. Run Indexing
    # We use 'scan_once' which is the standard entry point for initial scan.
    indexer = Indexer(cfg, db)
    
    # Pre-register roots as Indexer sees them (Crucial for FK constraints)
    # The indexer logic iterates cfg.workspace_roots, so we should do the same
    # or rely on Indexer's internal logic if it handles registration (it usually does).
    # But since we are manually controlling the flow, let's explicit register.
    for r in cfg.workspace_roots:
        rid = WorkspaceManager.root_id(r)
        try:
            db.upsert_root(rid, r, r)
        except Exception:
            pass # Already exists

    indexer.scan_once()
    
    # Wait for indexing to complete (using public status check)
    # In a real scenario, this would be async, but here we can drain the queue manually
    # by using the coordinator which is part of the Indexer's public interface logic
    while indexer.coordinator.fair_queue.qsize() > 0:
        item = indexer.coordinator.fair_queue.get()
        # We invoke the internal handler because we are simulating the worker thread here.
        # This is acceptable for flow testing without spawning threads.
        indexer._handle_task(item[0], item[1])
        
    # Force flush L1 buffer to storage
    indexer.stop()
    
    # Drain storage writer (flush pending commits)
    
    # Since we are not running the writer thread in this test, we must manually drain the queue
    writer = indexer.storage.writer
    tasks = writer._drain_batch(100)
    if tasks:
        with db._write:
            writer._process_batch(db._write.cursor(), tasks)
            db._write.commit()
    
    # 4. Verify Indexing Results (DB Layer)
    root_id = indexer._active_roots[0] if indexer._active_roots else WorkspaceManager.root_id(ws_path)
    files = db.search_files("")
    
    assert len(files) >= 2
    # The 'path' field usually contains 'root_id/rel_path' or absolute path depending on impl.
    # We check if the expected relative path is part of the stored path.
    paths = [f['path'] for f in files]
    assert any("src/main.py" in p for p in paths)
    assert any("README.md" in p for p in paths)
    
    # 5. Verify Search (Engine Layer)
    engine = SearchEngine(db)
    
    # Test 5-1: Keyword Search
    opts = SearchOptions(query="hello", root_ids=[root_id])
    hits, meta = engine.search_v2(opts)
    assert len(hits) >= 1
    assert hits[0].path.endswith("src/main.py")
    
    # Test 5-2: FTS Fallback (Implicitly tested if Tantivy is not present)
    opts_fts = SearchOptions(query="Project", root_ids=[root_id])
    hits_fts, _ = engine.search_v2(opts_fts)
    assert len(hits_fts) >= 1
    assert hits_fts[0].path.endswith("README.md")

def test_config_loading(temp_workspace):
    """Verifies that configuration is loaded correctly from the workspace."""
    cfg = Config.load(None, workspace_root_override=str(temp_workspace))
    assert cfg.workspace_root == str(temp_workspace)
    assert ".git" in cfg.exclude_dirs
