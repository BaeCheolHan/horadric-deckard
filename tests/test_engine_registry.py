import os

from sari.core.engine_registry import default_engine_name, get_registry, get_default_engine
from sari.core.engine_runtime import EmbeddedEngine
from sari.core.search_engine import SqliteSearchEngineAdapter


def test_default_engine_name(monkeypatch):
    monkeypatch.delenv("SARI_ENGINE_MODE", raising=False)
    assert default_engine_name() == "embedded"
    monkeypatch.setenv("SARI_ENGINE_MODE", "embedded")
    assert default_engine_name() == "embedded"


def test_registry_create_sqlite(monkeypatch):
    registry = get_registry()
    class DummyDB: pass
    engine = registry.create("sqlite", DummyDB())
    assert hasattr(engine, "search_v2")
    try:
        registry.create("missing", DummyDB())
    except KeyError:
        pass


def test_get_default_engine_embedded(monkeypatch, tmp_path):
    class DummyCfg:
        workspace_roots = [str(tmp_path)]
    class DummyDB:
        pass
    monkeypatch.setenv("SARI_ENGINE_MODE", "embedded")
    eng = get_default_engine(DummyDB(), DummyCfg(), DummyCfg.workspace_roots)
    assert isinstance(eng, EmbeddedEngine)
    monkeypatch.delenv("SARI_ENGINE_MODE", raising=False)


def test_get_default_engine_sqlite(monkeypatch):
    class DummyDB:
        pass
    monkeypatch.setenv("SARI_ENGINE_MODE", "sqlite")
    eng = get_default_engine(DummyDB(), None, None)
    assert isinstance(eng, SqliteSearchEngineAdapter)
