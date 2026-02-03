import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from .models import SearchHit, SearchOptions
    from .ranking import get_file_extension, snippet_around
    from .workspace import WorkspaceManager
except ImportError:
    from models import SearchHit, SearchOptions
    from ranking import get_file_extension, snippet_around
    from workspace import WorkspaceManager


ENGINE_PACKAGE = os.environ.get("DECKARD_ENGINE_PACKAGE", "tantivy==0.22.0")
_DEFAULT_ENGINE_MEM_MB = 512
_DEFAULT_ENGINE_INDEX_MEM_MB = 256
_DEFAULT_ENGINE_THREADS = 2


class EngineError(RuntimeError):
    def __init__(self, code: str, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint or ""


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    norm = unicodedata.normalize("NFKC", text)
    norm = norm.lower()
    norm = " ".join(norm.split())
    return norm


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _query_parts(q: str) -> Tuple[List[str], List[str]]:
    parts = re.split(r"\"([^\"]+)\"", q)
    tokens: List[str] = []
    phrases: List[str] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            if part.strip():
                phrases.append(part.strip())
        else:
            tokens.extend([p for p in part.strip().split() if p])
    return tokens, phrases


def _has_cjk(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3040 <= code <= 0x30FF:
            return True
    return False


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _inject_venv_site_packages(venv_dir: Path) -> None:
    major = sys.version_info.major
    minor = sys.version_info.minor
    if os.name == "nt":
        sp = venv_dir / "Lib" / "site-packages"
    else:
        sp = venv_dir / "lib" / f"python{major}.{minor}" / "site-packages"
    if sp.exists():
        sys.path.insert(0, str(sp))


def _ensure_venv(venv_dir: Path) -> None:
    if venv_dir.exists():
        return
    import venv
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True).create(str(venv_dir))


def _install_engine_package(venv_dir: Path) -> None:
    _ensure_venv(venv_dir)
    py = _venv_python(venv_dir)
    subprocess.check_call([str(py), "-m", "pip", "install", ENGINE_PACKAGE])


def _load_tantivy(venv_dir: Path, auto_install: bool) -> Any:
    try:
        import tantivy  # type: ignore
        return tantivy
    except Exception:
        if not auto_install:
            raise EngineError("ERR_ENGINE_NOT_INSTALLED", "Engine not installed", "sari --cmd engine install")
        _install_engine_package(venv_dir)
        _inject_venv_site_packages(venv_dir)
        try:
            import tantivy  # type: ignore
            return tantivy
        except Exception as exc:
            raise EngineError("ERR_ENGINE_NOT_INSTALLED", f"Engine install failed: {exc}", "sari --cmd engine install")


@dataclass
class EngineMeta:
    engine_mode: str
    engine_ready: bool
    engine_version: str
    index_version: str
    reason: str = ""
    hint: str = ""
    doc_count: int = 0
    index_size_bytes: int = 0
    last_build_ts: int = 0
    engine_mem_mb: int = 0
    index_mem_mb: int = 0
    engine_threads: int = 0


class EmbeddedEngine:
    def __init__(self, db: Any, cfg: Any, roots: List[str]):
        self._db = db
        self._cfg = cfg
        self._roots = roots
        self._root_ids = [WorkspaceManager.root_id(r) for r in roots]
        self._roots_hash = WorkspaceManager.roots_hash(self._root_ids)
        self._index_dir = WorkspaceManager.get_engine_index_dir(self._roots_hash)
        self._cache_dir = WorkspaceManager.get_engine_cache_dir()
        self._venv_dir = WorkspaceManager.get_engine_venv_dir()
        self._index_version_path = self._index_dir / "index_version.json"
        self._auto_install = (os.environ.get("DECKARD_ENGINE_AUTO_INSTALL", "1").strip().lower() not in {"0", "false", "no", "off"})
        self._tantivy = None
        self._index = None
        self._schema = None
        self._fields: Dict[str, Any] = {}

    def _engine_limits(self) -> Tuple[int, int, int]:
        mem_mb = _env_int("DECKARD_ENGINE_MEM_MB", _DEFAULT_ENGINE_MEM_MB)
        index_mem_mb = _env_int("DECKARD_ENGINE_INDEX_MEM_MB", _DEFAULT_ENGINE_INDEX_MEM_MB)
        threads = _env_int("DECKARD_ENGINE_THREADS", _DEFAULT_ENGINE_THREADS)
        mem_mb = max(64, mem_mb)
        index_mem_mb = max(64, index_mem_mb)
        if index_mem_mb > mem_mb:
            index_mem_mb = mem_mb
        max_threads = max(1, os.cpu_count() or 1)
        if threads < 1:
            threads = 1
        if threads > max_threads:
            threads = max_threads
        return mem_mb, index_mem_mb, threads

    def _index_writer(self, index: Any) -> Any:
        _mem_mb, index_mem_mb, threads = self._engine_limits()
        budget = int(index_mem_mb) * 1024 * 1024
        try:
            return index.writer(budget, threads)
        except TypeError:
            try:
                return index.writer(budget)
            except TypeError:
                return index.writer()

    def _engine_version(self) -> str:
        if not self._tantivy:
            return "unknown"
        return getattr(self._tantivy, "__version__", "unknown")

    def _config_hash(self) -> str:
        payload = {
            "root_ids": sorted(self._root_ids),
            "include_ext": list(getattr(self._cfg, "include_ext", [])),
            "include_files": list(getattr(self._cfg, "include_files", [])),
            "exclude_dirs": list(getattr(self._cfg, "exclude_dirs", [])),
            "exclude_globs": list(getattr(self._cfg, "exclude_globs", [])),
            "max_file_bytes": int(getattr(self._cfg, "max_file_bytes", 0) or 0),
            "size_profile": (os.environ.get("DECKARD_SIZE_PROFILE") or "default").strip().lower(),
            "max_parse_bytes": int(os.environ.get("DECKARD_MAX_PARSE_BYTES", "0") or 0),
            "max_ast_bytes": int(os.environ.get("DECKARD_MAX_AST_BYTES", "0") or 0),
            "follow_symlinks": (os.environ.get("DECKARD_FOLLOW_SYMLINKS", "0").strip().lower() in ("1", "true", "yes", "on")),
            "engine_version": self._engine_version(),
            "max_doc_bytes": int(os.environ.get("DECKARD_ENGINE_MAX_DOC_BYTES", "4194304") or 4194304),
            "preview_bytes": int(os.environ.get("DECKARD_ENGINE_PREVIEW_BYTES", "8192") or 8192),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _load_index_version(self) -> Dict[str, Any]:
        if not self._index_version_path.exists():
            return {}
        try:
            return json.loads(self._index_version_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_index_version(self, doc_count: int) -> None:
        meta = {
            "version": 1,
            "build_ts": int(time.time()),
            "doc_count": int(doc_count),
            "engine_version": self._engine_version(),
            "config_hash": self._config_hash(),
        }
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._index_version_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _ensure_index(self) -> None:
        self._tantivy = _load_tantivy(self._venv_dir, self._auto_install)
        if self._schema and self._index:
            return
        schema_builder = self._tantivy.SchemaBuilder()
        self._fields = {
            "doc_id": schema_builder.add_text_field("doc_id", stored=True),
            "path": schema_builder.add_text_field("path", stored=True),
            "repo": schema_builder.add_text_field("repo", stored=True),
            "root_id": schema_builder.add_text_field("root_id", stored=True),
            "rel_path": schema_builder.add_text_field("rel_path", stored=True),
            "path_text": schema_builder.add_text_field("path_text"),
            "body_text": schema_builder.add_text_field("body_text"),
            "preview": schema_builder.add_text_field("preview", stored=True),
            "mtime": schema_builder.add_i64_field("mtime", stored=True),
            "size": schema_builder.add_i64_field("size", stored=True),
        }
        self._schema = schema_builder.build()
        if self._index_dir.exists() and (self._index_dir / "meta.json").exists():
            self._index = self._tantivy.Index(self._index_dir.as_posix())
        else:
            self._index_dir.mkdir(parents=True, exist_ok=True)
            self._index = self._tantivy.Index(self._schema, self._index_dir.as_posix())

    def status(self) -> EngineMeta:
        mode = "embedded"
        mem_mb, index_mem_mb, threads = self._engine_limits()
        try:
            if not self._tantivy:
                self._tantivy = _load_tantivy(self._venv_dir, auto_install=False)
        except EngineError:
            return EngineMeta(
                engine_mode=mode,
                engine_ready=False,
                engine_version="unknown",
                index_version="",
                reason="NOT_INSTALLED",
                hint="sari --cmd engine install",
                engine_mem_mb=mem_mb,
                index_mem_mb=index_mem_mb,
                engine_threads=threads,
            )
        index_meta = self._load_index_version()
        engine_version = index_meta.get("engine_version", "")
        cfg_hash = index_meta.get("config_hash", "")
        ready = bool(index_meta) and cfg_hash == self._config_hash() and engine_version
        reason = ""
        hint = ""
        if not index_meta:
            ready = False
            reason = "INDEX_MISSING"
            hint = "sari --cmd engine rebuild"
        elif cfg_hash != self._config_hash():
            ready = False
            reason = "CONFIG_MISMATCH"
            hint = "sari --cmd engine rebuild"
        if not engine_version:
            ready = False
            reason = "ENGINE_MISMATCH"
            hint = "sari --cmd engine rebuild"
        idx_size = 0
        if self._index_dir.exists():
            try:
                idx_size = sum(p.stat().st_size for p in self._index_dir.rglob("*") if p.is_file())
            except Exception:
                idx_size = 0
        return EngineMeta(
            engine_mode=mode,
            engine_ready=ready,
            engine_version=engine_version or "unknown",
            index_version=cfg_hash or "",
            reason=reason,
            hint=hint,
            doc_count=int(index_meta.get("doc_count", 0) or 0),
            index_size_bytes=idx_size,
            last_build_ts=int(index_meta.get("build_ts", 0) or 0),
            engine_mem_mb=mem_mb,
            index_mem_mb=index_mem_mb,
            engine_threads=threads,
        )

    def install(self) -> None:
        _load_tantivy(self._venv_dir, auto_install=True)
        self._ensure_index()

    def rebuild(self) -> None:
        self._ensure_index()
        tmp_dir = self._index_dir.parent / f"{self._index_dir.name}.build"
        if tmp_dir.exists():
            for p in tmp_dir.rglob("*"):
                if p.is_file():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        if tmp_dir.exists():
            try:
                tmp_dir.rmdir()
            except Exception:
                pass
        tmp_dir.mkdir(parents=True, exist_ok=True)
        idx = self._tantivy.Index(self._schema, tmp_dir.as_posix())
        writer = self._index_writer(idx)
        count = 0
        for doc in self._db.iter_engine_documents(self._root_ids):
            writer.add_document(self._tantivy.Document(**doc))
            count += 1
        writer.commit()
        idx.reload()
        if self._index_dir.exists():
            for p in self._index_dir.rglob("*"):
                if p.is_file():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        if self._index_dir.exists():
            try:
                self._index_dir.rmdir()
            except Exception:
                pass
        tmp_dir.replace(self._index_dir)
        self._index = idx
        self._write_index_version(count)

    def upsert_documents(self, docs: Iterable[Dict[str, Any]]) -> None:
        self._ensure_index()
        writer = self._index_writer(self._index)
        count = 0
        for doc in docs:
            doc_id = doc.get("doc_id")
            if doc_id:
                term = self._tantivy.Term.from_field_text(self._fields["doc_id"], doc_id)
                writer.delete_term(term)
            writer.add_document(self._tantivy.Document(**doc))
            count += 1
        writer.commit()
        if count:
            self._write_index_version(self._load_index_version().get("doc_count", 0) + count)

    def delete_documents(self, doc_ids: Iterable[str]) -> None:
        self._ensure_index()
        writer = self._index_writer(self._index)
        deleted = 0
        for doc_id in doc_ids:
            term = self._tantivy.Term.from_field_text(self._fields["doc_id"], doc_id)
            writer.delete_term(term)
            deleted += 1
        if deleted:
            writer.commit()
            meta = self._load_index_version()
            doc_count = int(meta.get("doc_count", 0) or 0)
            doc_count = max(0, doc_count - deleted)
            self._write_index_version(doc_count)

    def search_v2(self, opts: SearchOptions) -> Tuple[List[SearchHit], Dict[str, Any]]:
        self._ensure_index()
        meta = {"total_mode": "approx", "total": -1}
        norm_q = _normalize_text(opts.query or "")
        if not norm_q:
            return [], meta
        tokens, phrases = _query_parts(norm_q)
        pieces = []
        for p in phrases:
            pieces.append(f"\"{p}\"")
        for t in tokens:
            pieces.append(t)
        qstr = " AND ".join(pieces) if pieces else ""
        if not qstr:
            return [], meta
        qp = self._tantivy.QueryParser.for_index(self._index, [self._fields["body_text"], self._fields["path_text"]])
        try:
            qp.set_conjunction_by_default()
        except Exception:
            pass
        query = qp.parse_query(qstr)
        searcher = self._index.searcher()
        limit = max(1, min(int(opts.limit), 50))
        top_docs = searcher.search(query, self._tantivy.TopDocs(limit=limit + int(opts.offset)))
        hits: List[SearchHit] = []
        for score, doc_address in top_docs:
            doc = searcher.doc(doc_address)
            path = doc.get_first(self._fields["path"])
            repo = doc.get_first(self._fields["repo"]) or "__root__"
            mtime = int(doc.get_first(self._fields["mtime"]) or 0)
            size = int(doc.get_first(self._fields["size"]) or 0)
            preview = doc.get_first(self._fields["preview"]) or ""
            path_str = str(path) if path else ""
            if opts.root_ids:
                rid = doc.get_first(self._fields["root_id"]) or ""
                if rid not in opts.root_ids:
                    continue
            if opts.repo and repo != opts.repo:
                continue
            if opts.file_types and get_file_extension(path_str) not in [ft.lower().lstrip(".") for ft in opts.file_types]:
                continue
            if opts.path_pattern and not _path_pattern_match(path_str, opts.path_pattern):
                continue
            if opts.exclude_patterns and _exclude_pattern_match(path_str, opts.exclude_patterns):
                continue
            snippet = snippet_around(preview, tokens, opts.snippet_lines, highlight=True) if preview else ""
            hits.append(SearchHit(
                repo=repo,
                path=path_str,
                score=float(score),
                snippet=snippet,
                mtime=mtime,
                size=size,
                match_count=0,
                file_type=get_file_extension(path_str),
                hit_reason="Engine match",
            ))
        hits.sort(key=lambda h: (-h.score, -h.mtime, h.path))
        start = int(opts.offset)
        end = start + limit
        return hits[start:end], meta

    def repo_candidates(self, q: str, limit: int = 3, root_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        q = (q or "").strip()
        if not q:
            return []
        sql = "SELECT repo, COUNT(1) AS c FROM files WHERE content LIKE ? ESCAPE '^' GROUP BY repo ORDER BY c DESC LIMIT ?;"
        like_q = q.replace("^", "^^").replace("%", "^%").replace("_", "^_")
        with self._db._read_lock:
            rows = self._db._read.execute(sql, (f"%{like_q}%", limit)).fetchall()
        out = []
        for r in rows:
            repo, c = str(r["repo"]), int(r["c"])
            out.append({"repo": repo, "score": c, "evidence": ""})
        return out


def _path_pattern_match(path: str, pattern: str) -> bool:
    import fnmatch
    p = path.replace("\\", "/")
    pat = pattern.replace("\\", "/")
    if pat.startswith("/"):
        if p.startswith(pat):
            return True
    if p.endswith("/" + pat) or p == pat:
        return True
    return fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, f"*/{pat}") or fnmatch.fnmatch(p, f"*/{pat}/*")


def _exclude_pattern_match(path: str, patterns: List[str]) -> bool:
    import fnmatch
    for p in patterns:
        if p in path or fnmatch.fnmatch(path, f"*{p}*"):
            return True
    return False
