import pytest
from unittest.mock import MagicMock, patch
from sari.core.engine_runtime import EngineRuntime, EngineRouter, EmbeddedEngine, SqliteSearchEngineAdapter
from sari.core.engine.tantivy_engine import TantivyEngine

def test_engine_router():
    engine1 = MagicMock()
    engine2 = MagicMock()
    router = EngineRouter({"root1": engine1, "root2": engine2})
    
    # Upsert
    docs = [{"doc_id": "root1/f1.py"}, {"doc_id": "root2/f2.js"}]
    router.upsert_documents(docs)
    assert engine1.upsert_documents.called
    assert engine2.upsert_documents.called
    
    # Delete
    router.delete_documents(["root1/f1.py"])
    assert engine1.delete_documents.called
    
    # Search
    engine1.search.return_value = [{"score": 0.9}]
    engine2.search.return_value = [{"score": 0.8}]
    results = router.search("query")
    assert len(results) == 2
    assert results[0]["score"] == 0.9

def test_sqlite_adapter():
    db = MagicMock()
    adapter = SqliteSearchEngineAdapter(db)
    status = adapter.status()
    assert status.engine_mode == "sqlite"
    assert status.engine_ready is True

def test_engine_runtime_init():
    with patch('sari.core.workspace.WorkspaceManager.root_id', return_value="root1"):
        runtime = EngineRuntime(["/tmp/ws"])
        assert runtime.root_ids == ["root1"]
        assert runtime.status().engine_ready is False

def test_embedded_engine_status():
    db = MagicMock()
    cfg = MagicMock()
    with patch('sari.core.workspace.WorkspaceManager.root_id', return_value="root1"):
        with patch('sari.core.engine_runtime.EngineRuntime.initialize'):
            engine = EmbeddedEngine(db, cfg, ["/tmp/ws"])
            status = engine.status()
            assert status.engine_mode == "embedded"


@pytest.mark.gate
def test_tantivy_upsert_accepts_id_key():
    class FakeWriter:
        def __init__(self):
            self.deleted = []
            self.added = []
        def delete_documents(self, field, value):
            self.deleted.append((field, value))
        def add_document(self, doc):
            self.added.append(doc)
        def commit(self):
            pass

    class FakeIndex:
        def __init__(self, writer):
            self._writer = writer
        def writer(self, *_args, **_kwargs):
            return self._writer

    fake_writer = FakeWriter()
    engine = TantivyEngine.__new__(TantivyEngine)
    engine._index = FakeIndex(fake_writer)
    engine._writer = None
    engine._writer_lock = __import__("threading").Lock()
    engine.settings = MagicMock()
    engine.settings.ENGINE_INDEX_MEM_MB = 64
    engine.logger = None

    with patch("sari.core.engine.tantivy_engine.tantivy") as mock_tantivy:
        mock_tantivy.Document.side_effect = lambda **kwargs: kwargs
        engine.upsert_documents([{"id": "root1/file.py", "repo": "repo1"}])

    assert ("path", "root1/file.py") in fake_writer.deleted
    assert len(fake_writer.added) == 1
