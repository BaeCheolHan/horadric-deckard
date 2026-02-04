import json
import os
import threading
from pathlib import Path
import sys
import types

from sari.core import engine_runtime
from sari.core.engine_runtime import EmbeddedEngine, EngineError


class DummyCfg:
    include_ext = []
    include_files = []
    exclude_dirs = []
    exclude_globs = []
    max_file_bytes = 0


class DummyDB:
    def iter_engine_documents(self, _root_ids):
        return []

    def __init__(self):
        self._read = sqlite3_connect()
        try:
            import sqlite3
            self._read.row_factory = sqlite3.Row
        except Exception:
            self._read.row_factory = None
        self._read_lock = threading.Lock()


def sqlite3_connect():
    import sqlite3
    return sqlite3.connect(":memory:")

class DummyIndex:
    def __init__(self):
        self.args = None

    def writer(self, *args):
        self.args = args
        return object()

class FakeDocument(dict):
    def get_first(self, field):
        return self.get(field)


class FakeWriter:
    def __init__(self, index):
        self._index = index

    def add_document(self, doc):
        self._index.docs.append(doc)

    def delete_term(self, _term):
        return None

    def commit(self):
        return None


class FakeSearcher:
    def __init__(self, index):
        self._index = index

    def search(self, _query, topdocs):
        limit = getattr(topdocs, "limit", len(self._index.docs))
        return [(1.0, idx) for idx, _ in enumerate(self._index.docs[:limit])]

    def doc(self, address):
        return self._index.docs[address]


class FakeIndex:
    def __init__(self, schema_or_path, path=None):
        self.schema = schema_or_path if path is not None else {}
        self.path = path if path is not None else schema_or_path
        self.docs = []

    def writer(self, *args):
        return FakeWriter(self)

    def reload(self):
        return None

    def searcher(self):
        return FakeSearcher(self)


class FakeSchemaBuilder:
    def __init__(self):
        self.fields = {}

    def add_text_field(self, name, stored=False):
        self.fields[name] = name
        return name

    def add_i64_field(self, name, stored=False):
        self.fields[name] = name
        return name

    def build(self):
        return self.fields


class FakeQueryParser:
    def __init__(self, index, fields):
        self.index = index
        self.fields = fields

    @classmethod
    def for_index(cls, index, fields):
        return cls(index, fields)

    def set_conjunction_by_default(self):
        return None

    def parse_query(self, qstr):
        return qstr


class FakeTopDocs:
    def __init__(self, limit=10):
        self.limit = limit


class FakeTerm:
    @classmethod
    def from_field_text(cls, field, text):
        return (field, text)


class FakeTantivy:
    __version__ = "0.0"
    SchemaBuilder = FakeSchemaBuilder
    Index = FakeIndex
    QueryParser = FakeQueryParser
    TopDocs = FakeTopDocs
    Term = FakeTerm
    Document = FakeDocument

def test_query_helpers():
    tokens, phrases = engine_runtime._query_parts('alpha \"beta gamma\" delta')
    assert tokens == ["alpha", "delta"]
    assert phrases == ["beta gamma"]
    assert engine_runtime._normalize_text("  A  B ") == "a b"
    assert engine_runtime._has_cjk("\u3042") is True


def test_path_pattern_and_exclude_match():
    assert engine_runtime._path_pattern_match("src/app.py", "app.py") is True
    assert engine_runtime._exclude_pattern_match("src/app.py", ["app.py"]) is True


def test_cjk_space_helpers():
    assert engine_runtime._cjk_space("hello") == "hello"
    assert engine_runtime._cjk_space("한글") == "한 글"
    assert engine_runtime._cjk_space("hello한글world") == "hello 한 글 world"


def test_resolve_body_tokenizer_env(monkeypatch, tmp_path):
    eng = engine_runtime.EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    monkeypatch.setenv("SARI_ENGINE_TOKENIZER", "latin")
    assert eng._resolve_body_tokenizer() == "tokenizer_latin"
    monkeypatch.setenv("SARI_ENGINE_TOKENIZER", "cjk")
    assert eng._resolve_body_tokenizer() == "tokenizer_cjk"
    monkeypatch.setenv("SARI_ENGINE_TOKENIZER", "auto")
    assert eng._resolve_body_tokenizer() == "tokenizer_cjk"


def test_register_tokenizers_best_effort(tmp_path):
    class FakeIndex:
        def __init__(self):
            self.registered = []

        def register_tokenizer(self, name, _analyzer):
            self.registered.append(name)

    class FakeTokenizer:
        @staticmethod
        def regex(_pattern):
            return ("regex", _pattern)

    class FakeFilter:
        @staticmethod
        def lowercase():
            return ("lowercase",)

    class FakeTextAnalyzerBuilder:
        def __init__(self, _tok):
            self._tok = _tok
            self._filters = []

        def filter(self, f):
            self._filters.append(f)
            return self

        def build(self):
            return {"tok": self._tok, "filters": self._filters}

    class FakeTantivy:
        Tokenizer = FakeTokenizer
        Filter = FakeFilter
        TextAnalyzerBuilder = FakeTextAnalyzerBuilder

    eng = engine_runtime.EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    eng._tantivy = FakeTantivy
    idx = FakeIndex()
    eng._register_tokenizers(idx)
    assert "tokenizer_latin" in idx.registered
    assert "tokenizer_cjk" in idx.registered


def test_engine_limits_clamp(monkeypatch, tmp_path):
    monkeypatch.setenv("SARI_ENGINE_MEM_MB", "128")
    monkeypatch.setenv("SARI_ENGINE_INDEX_MEM_MB", "512")
    monkeypatch.setenv("SARI_ENGINE_THREADS", "999")
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    mem_mb, index_mem_mb, threads = eng._engine_limits()
    assert mem_mb == 128
    assert index_mem_mb == 64
    assert threads >= 1


def test_engine_status_not_installed(monkeypatch, tmp_path):
    def _raise(_venv, auto_install):
        raise EngineError("ERR_ENGINE_NOT_INSTALLED", "not installed")

    monkeypatch.setattr(engine_runtime, "_load_tantivy", _raise)
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    st = eng.status()
    assert st.engine_ready is False
    assert st.reason == "NOT_INSTALLED"


def test_engine_index_writer_signature(monkeypatch, tmp_path):
    monkeypatch.setenv("SARI_ENGINE_INDEX_MEM_MB", "64")
    monkeypatch.setenv("SARI_ENGINE_THREADS", "2")
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    idx = DummyIndex()
    _ = eng._index_writer(idx)
    assert idx.args is not None
    assert len(idx.args) >= 1


def test_engine_index_version_write(tmp_path, monkeypatch):
    monkeypatch.setenv("SARI_ENGINE_MEM_MB", "128")
    monkeypatch.setenv("SARI_ENGINE_INDEX_MEM_MB", "64")
    monkeypatch.setenv("SARI_ENGINE_THREADS", "1")
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    eng._index_dir = tmp_path / "idx"
    eng._index_version_path = eng._index_dir / "index_version.json"
    eng._write_index_version(3)
    assert eng._index_version_path.exists()
    data = json.loads(eng._index_version_path.read_text(encoding="utf-8"))
    assert data["doc_count"] == 3


def test_engine_search_and_rebuild(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_runtime, "_load_tantivy", lambda _venv, auto_install: FakeTantivy)
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    eng._index_dir = tmp_path / "idx"
    eng._index_version_path = eng._index_dir / "index_version.json"
    eng.install()
    eng.upsert_documents([{
        "doc_id": "root-aaaa/a.txt",
        "path": "root-aaaa/a.txt",
        "repo": "__root__",
        "root_id": "root-aaaa",
        "rel_path": "a.txt",
        "path_text": "a.txt",
        "body_text": "hello world",
        "preview": "hello world",
        "mtime": 1,
        "size": 1,
    }])
    hits, meta = eng.search_v2(engine_runtime.SearchOptions(query="hello", limit=5, offset=0))
    assert hits
    assert meta["total_mode"] == "approx"
    eng.delete_documents(["root-aaaa/a.txt"])
    eng.rebuild()


def test_engine_search_filters(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_runtime, "_load_tantivy", lambda _venv, auto_install: FakeTantivy)
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    eng._index_dir = tmp_path / "idx"
    eng._index_version_path = eng._index_dir / "index_version.json"
    eng.install()
    eng.upsert_documents([
        {
            "doc_id": "root-aaaa/a.txt",
            "path": "root-aaaa/a.txt",
            "repo": "repo",
            "root_id": "root-aaaa",
            "rel_path": "a.txt",
            "path_text": "a.txt",
            "body_text": "hello world",
            "preview": "hello world",
            "mtime": 1,
            "size": 1,
        },
        {
            "doc_id": "root-bbbb/skip.log",
            "path": "root-bbbb/skip.log",
            "repo": "repo",
            "root_id": "root-bbbb",
            "rel_path": "skip.log",
            "path_text": "skip.log",
            "body_text": "hello world",
            "preview": "hello world",
            "mtime": 2,
            "size": 2,
        },
    ])
    opts = engine_runtime.SearchOptions(
        query="hello",
        limit=5,
        offset=0,
        root_ids=["root-aaaa"],
        repo="repo",
        file_types=["txt"],
        path_pattern="a.txt",
        exclude_patterns=["skip"],
    )
    hits, _ = eng.search_v2(opts)
    assert len(hits) == 1
    assert hits[0].path == "root-aaaa/a.txt"


def test_engine_config_hash_and_load_index(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_runtime, "_load_tantivy", lambda _venv, auto_install: FakeTantivy)
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    eng._index_dir = tmp_path / "idx"
    eng._index_version_path = eng._index_dir / "index_version.json"
    h = eng._config_hash()
    assert len(h) == 40
    eng._index_dir.mkdir(parents=True, exist_ok=True)
    eng._index_version_path.write_text("invalid", encoding="utf-8")
    assert eng._load_index_version() == {}


def test_engine_status_variants(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_runtime, "_load_tantivy", lambda _venv, auto_install: FakeTantivy)
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    eng._index_dir = tmp_path / "idx"
    eng._index_version_path = eng._index_dir / "index_version.json"
    st = eng.status()
    assert st.reason in {"INDEX_MISSING", "ENGINE_MISMATCH", "CONFIG_MISMATCH"}

    eng._index_dir.mkdir(parents=True, exist_ok=True)
    eng._index_version_path.write_text(json.dumps({
        "version": 1,
        "build_ts": 1,
        "doc_count": 1,
        "engine_version": "0.0",
        "config_hash": "mismatch",
    }), encoding="utf-8")
    st2 = eng.status()
    assert st2.engine_ready is False


def test_engine_repo_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_runtime, "_load_tantivy", lambda _venv, auto_install: FakeTantivy)
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    db = eng._db
    db._read.execute("CREATE TABLE files (repo TEXT, content TEXT)")
    db._read.execute("INSERT INTO files (repo, content) VALUES (?,?)", ("repo", "hello"))
    db._read.commit()
    res = eng.repo_candidates("hello", limit=1, root_ids=None)
    assert res and res[0]["repo"] == "repo"


def test_venv_helpers(monkeypatch, tmp_path):
    venv_dir = tmp_path / "venv"
    called = {}

    class DummyBuilder:
        def __init__(self, with_pip=True):
            called["with_pip"] = with_pip
        def create(self, path):
            called["path"] = path

    monkeypatch.setitem(sys.modules, "venv", types.SimpleNamespace(EnvBuilder=DummyBuilder))
    engine_runtime._ensure_venv(venv_dir)
    assert called.get("path") == str(venv_dir)

    site_dir = venv_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site_dir.mkdir(parents=True, exist_ok=True)
    engine_runtime._inject_venv_site_packages(venv_dir)
    assert str(site_dir) in sys.path


def test_load_tantivy_paths(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tantivy", FakeTantivy)
    assert engine_runtime._load_tantivy(tmp_path, auto_install=False) == FakeTantivy
    monkeypatch.delitem(sys.modules, "tantivy", raising=False)

    def _no_install(_venv, auto_install):
        raise EngineError("ERR_ENGINE_NOT_INSTALLED", "nope")

    monkeypatch.setattr(engine_runtime, "_install_engine_package", lambda _venv: None)
    try:
        engine_runtime._load_tantivy(tmp_path, auto_install=False)
    except EngineError as exc:
        assert exc.code == "ERR_ENGINE_NOT_INSTALLED"


def test_ensure_index_existing(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_runtime, "_load_tantivy", lambda _venv, auto_install: FakeTantivy)
    eng = EmbeddedEngine(DummyDB(), DummyCfg(), [str(tmp_path)])
    eng._index_dir = tmp_path / "idx"
    eng._index_version_path = eng._index_dir / "index_version.json"
    eng._index_dir.mkdir(parents=True, exist_ok=True)
    (eng._index_dir / "meta.json").write_text("{}", encoding="utf-8")
    eng._ensure_index()
    assert eng._index is not None
