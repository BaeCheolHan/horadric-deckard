import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from sari.core.indexer.main import Indexer, BrokenProcessPool
from sari.core.queue_pipeline import FsEvent, FsEventKind

@pytest.fixture
def mock_indexer(tmp_path):
    cfg = MagicMock()
    # Set attributes BEFORE Indexer creation
    cfg.workspace_roots = [str(tmp_path)]
    cfg.include_ext = [".py", ".js"]
    cfg.include_files = []
    cfg.exclude_dirs = []
    cfg.exclude_globs = []
    
    db = MagicMock()
    mock_settings = MagicMock()
    mock_settings.FOLLOW_SYMLINKS = False
    mock_settings.INDEX_MEM_MB = 1024
    mock_settings.INDEX_WORKERS = 2
    mock_settings.MAX_DEPTH = 30
    mock_settings.get_int.side_effect = lambda key, default: default
    mock_settings.WATCHER_MONITOR_SECONDS = 10
    
    # Scanner uses cfg.settings or global_settings
    cfg.settings = mock_settings
    cfg.max_depth = 30
    
    with patch('sari.core.db.storage.GlobalStorageManager.get_instance') as mock_get_storage:
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        indexer = Indexer(cfg, db, settings_obj=mock_settings)
        indexer.storage = mock_storage
        return indexer

def test_indexer_init(mock_indexer):
    assert mock_indexer.status.index_ready is False

def test_indexer_init_falls_back_when_process_pool_unavailable(tmp_path):
    cfg = MagicMock()
    cfg.workspace_roots = [str(tmp_path)]
    cfg.include_ext = [".py"]
    cfg.include_files = []
    cfg.exclude_dirs = []
    cfg.exclude_globs = []
    cfg.max_depth = 30

    db = MagicMock()
    mock_settings = MagicMock()
    mock_settings.FOLLOW_SYMLINKS = False
    mock_settings.INDEX_MEM_MB = 1024
    mock_settings.INDEX_WORKERS = 2
    mock_settings.MAX_DEPTH = 30
    mock_settings.get_int.side_effect = lambda key, default: default
    cfg.settings = mock_settings

    with patch('sari.core.db.storage.GlobalStorageManager.get_instance') as mock_get_storage, \
         patch('sari.core.indexer.main.concurrent.futures.ProcessPoolExecutor', side_effect=PermissionError("blocked")):
        mock_get_storage.return_value = MagicMock()
        idx = Indexer(cfg, db, settings_obj=mock_settings)
        assert idx._use_process_pool is False
        assert idx._executor is None

def test_indexer_scan_once(mock_indexer, tmp_path):
    (tmp_path / "file1.py").write_text("print(1)")
    mock_indexer.scan_once()
    tasks = []
    while True:
        task = mock_indexer.coordinator.get_next_task()
        if not task: break
        tasks.append(task)
    assert len(tasks) >= 1

def test_indexer_handle_task(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    path = root / "test.py"
    path.write_text("def hello(): pass")
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(root))
    
    task = {"kind": "scan_file", "root": root, "path": path, "st": path.stat(), "scan_ts": 1000, "excluded": False}
    mock_indexer.worker.process_file_task = MagicMock(return_value={
        "type": "changed", "rel": f"{root_id}/test.py", "repo": "repo1",
        "mtime": 100, "size": 50, "content": "def hello(): pass",
        "parse_status": "ok", "parse_reason": "", "ast_status": "ok", "ast_reason": "",
        "is_binary": False, "is_minified": False, "symbols": []
    })
    
    mock_indexer._handle_task(root_id, task)
    assert root_id in mock_indexer._l1_buffer
    assert mock_indexer.status.indexed_files == 1

def test_indexer_l1_flush(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(root))
    mock_indexer._l1_max_size = 2
    
    # Pre-populate to avoid KeyError
    from collections import OrderedDict
    mock_indexer._l1_buffer[root_id] = OrderedDict()
    
    def add_file(name):
        path = root / name
        path.write_text("content")
        mock_indexer.worker.process_file_task = MagicMock(return_value={
            "type": "changed", "rel": f"{root_id}/{name}", "repo": "repo",
            "mtime": 100, "size": 7, "content": "content",
            "parse_status": "ok", "parse_reason": "", "ast_status": "none", "ast_reason": "",
            "is_binary": False, "is_minified": False
        })
        mock_indexer._handle_task(root_id, {"kind": "scan_file", "root": root, "path": path, "st": path.stat(), "scan_ts": 100, "excluded": False})

    add_file("f1.py")
    add_file("f2.py") 
    assert mock_indexer.storage.enqueue_task.called


def test_indexer_delete_event_uses_workspace_root_id(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    deleted = root / "gone.py"
    deleted.write_text("x")
    deleted.unlink()

    with patch("sari.core.workspace.WorkspaceManager.root_id", return_value="root-legacy"), \
         patch("sari.core.workspace.WorkspaceManager.root_id_for_workspace", return_value="root-explicit"):
        mock_indexer._enqueue_fsevent(FsEvent(kind=FsEventKind.DELETED, path=str(deleted), root=str(root)))

    called_path = mock_indexer.storage.delete_file.call_args.kwargs["path"]
    assert called_path.startswith("root-explicit/")
    assert called_path.endswith("gone.py")


def test_indexer_delete_event_without_root_infers_workspace(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    deleted = root / "lost.py"
    deleted.write_text("x")
    deleted.unlink()

    with patch("sari.core.workspace.WorkspaceManager.root_id_for_workspace", return_value="root-explicit"):
        mock_indexer._enqueue_fsevent(FsEvent(kind=FsEventKind.DELETED, path=str(deleted), root=""))

    called_path = mock_indexer.storage.delete_file.call_args.kwargs["path"]
    assert called_path == "root-explicit/lost.py"


def test_indexer_moved_event_deletes_old_and_enqueues_new(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    src = root / "old.py"
    dst = root / "new.py"
    src.write_text("x")
    src.rename(dst)

    with patch("sari.core.workspace.WorkspaceManager.root_id_for_workspace", return_value="root-explicit"):
        mock_indexer._enqueue_fsevent(
            FsEvent(kind=FsEventKind.MOVED, path=str(src), root=str(root), dest_path=str(dst))
        )

    called_path = mock_indexer.storage.delete_file.call_args.kwargs["path"]
    assert called_path == "root-explicit/old.py"
    item = mock_indexer.coordinator.get_next_task()
    assert item is not None
    rid, task = item
    assert rid == "root-explicit"
    assert str(task["path"]).endswith("new.py")


def test_on_task_complete_success_path(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    path = root / "ok.py"
    path.write_text("print('ok')")
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(root))
    task = {"kind": "scan_file", "root": root, "path": path, "st": path.stat(), "scan_ts": 100, "excluded": False}

    class _DoneFuture:
        def result(self):
            return {
                "type": "changed", "rel": f"{root_id}/ok.py", "repo": "repo",
                "mtime": 100, "size": 10, "content": "print('ok')",
                "parse_status": "ok", "parse_reason": "", "ast_status": "ok", "ast_reason": "",
                "is_binary": False, "is_minified": False, "symbols": [], "relations": []
            }

    with patch.object(mock_indexer, "_finalize_file_indexing") as finalize:
        mock_indexer._on_task_complete(_DoneFuture(), root_id, task)
        assert finalize.called
        assert mock_indexer.status.errors == 0


def test_on_task_complete_failure_path(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    path = root / "bad.py"
    path.write_text("print('bad')")
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(root))
    task = {"kind": "scan_file", "root": root, "path": path, "st": path.stat(), "scan_ts": 100, "excluded": False}

    class _ErrFuture:
        def result(self):
            raise RuntimeError("boom")

    mock_indexer._on_task_complete(_ErrFuture(), root_id, task)
    assert mock_indexer.status.errors == 1


def test_worker_loop_submits_root_id_for_process_task(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    path = root / "proc.py"
    path.write_text("print('proc')")
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(root))
    task = {"kind": "scan_file", "root": root, "path": path, "st": path.stat(), "scan_ts": 100, "excluded": False}

    class _DoneFuture:
        def add_done_callback(self, cb):
            return None

    submitted = {}

    def _submit(fn, payload):
        submitted["payload"] = payload
        mock_indexer._stop.set()
        return _DoneFuture()

    mock_indexer._executor.submit = _submit
    mock_indexer.coordinator.get_next_task = MagicMock(side_effect=[(root_id, task), None])
    mock_indexer.storage.get_queue_load = MagicMock(return_value=0.0)
    mock_indexer.coordinator.get_sleep_penalty = MagicMock(return_value=0.0)

    mock_indexer._worker_loop()
    assert submitted["payload"]["root_id"] == root_id


def test_worker_loop_submit_failure_falls_back_to_sync(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    path = root / "fallback.py"
    path.write_text("print('fallback')")
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(root))
    task = {"kind": "scan_file", "root": root, "path": path, "st": path.stat(), "scan_ts": 100, "excluded": False}

    mock_indexer._executor.submit = MagicMock(side_effect=RuntimeError("pool down"))
    mock_indexer.coordinator.get_next_task = MagicMock(side_effect=[(root_id, task), None])
    mock_indexer.storage.get_queue_load = MagicMock(return_value=0.0)
    mock_indexer.coordinator.get_sleep_penalty = MagicMock(return_value=0.0)
    with patch.object(mock_indexer, "_handle_task") as handle_task:
        handle_task.side_effect = lambda *_args, **_kwargs: mock_indexer._stop.set()
        mock_indexer._worker_loop()
        assert handle_task.called
        assert mock_indexer._use_process_pool is False


def test_on_task_complete_broken_pool_disables_process_pool(mock_indexer, tmp_path):
    root = tmp_path.absolute()
    path = root / "broken.py"
    path.write_text("print('broken')")
    from sari.core.workspace import WorkspaceManager
    root_id = WorkspaceManager.root_id(str(root))
    task = {"kind": "scan_file", "root": root, "path": path, "st": path.stat(), "scan_ts": 100, "excluded": False}

    class _BrokenFuture:
        def result(self):
            raise BrokenProcessPool("terminated")

    with patch.object(mock_indexer, "_handle_task") as handle_task:
        mock_indexer._on_task_complete(_BrokenFuture(), root_id, task)
        assert handle_task.called
        assert mock_indexer._use_process_pool is False
