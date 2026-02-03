import gc
import tracemalloc

from app.engine_runtime import EmbeddedEngine
from app.engine_runtime import EngineError
from app import engine_runtime
from app.models import SearchHit, SearchOptions
from mcp.tools.search import execute_search


class DummyDB:
    def __init__(self):
        self._legacy = False

    def has_legacy_paths(self):
        return self._legacy


class DummyLogger:
    def log_telemetry(self, _msg):
        pass


class DummyEngine:
    def status(self):
        class S:
            engine_mode = "sqlite"
            engine_ready = True
            engine_version = "1.0"
            index_version = "v1"
        return S()

    def search_v2(self, opts):
        hit = SearchHit(
            repo="repo",
            path="root-aaaa/file.txt",
            score=1.0,
            snippet="match",
            mtime=0,
            size=1,
            match_count=1,
            file_type="txt",
        )
        return [hit], {"total": 1, "total_mode": opts.total_mode}


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


class DummyCfg:
    include_ext = []
    include_files = []
    exclude_dirs = []
    exclude_globs = []
    max_file_bytes = 0


class DummyDBEngineDocs:
    def iter_engine_documents(self, _root_ids):
        return [
            {
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
            }
        ]


def _mem_growth_bytes(before, after):
    stats = after.compare_to(before, "lineno")
    total_diff = sum(stat.size_diff for stat in stats)
    return max(0, total_diff)


def test_memory_search_tool_repeat(tmp_path):
    db = DummyDB()
    engine = DummyEngine()
    roots = [str(tmp_path)]

    tracemalloc.start()
    before = tracemalloc.take_snapshot()

    for _ in range(200):
        execute_search({"query": "hello", "limit": 5}, db, DummyLogger(), roots, engine=engine)

    gc.collect()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    growth = _mem_growth_bytes(before, after)
    assert growth < 2_000_000


def test_memory_engine_rebuild_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_runtime, "_load_tantivy", lambda _venv, auto_install: FakeTantivy)
    eng = EmbeddedEngine(DummyDBEngineDocs(), DummyCfg(), [str(tmp_path)])
    eng._index_dir = tmp_path / "idx"
    eng._index_version_path = eng._index_dir / "index_version.json"

    tracemalloc.start()
    before = tracemalloc.take_snapshot()

    for _ in range(5):
        eng.rebuild()
        eng.search_v2(SearchOptions(query="hello", limit=5, offset=0))

    gc.collect()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    growth = _mem_growth_bytes(before, after)
    assert growth < 5_000_000
