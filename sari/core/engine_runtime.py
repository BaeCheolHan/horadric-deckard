import hashlib
import json
import logging
import os
import platform
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
    from .cjk import has_cjk as _has_cjk, cjk_space as _cjk_space_impl, lindera_available, lindera_error
except ImportError:
    from models import SearchHit, SearchOptions
    from ranking import get_file_extension, snippet_around
    from workspace import WorkspaceManager
    from cjk import has_cjk as _has_cjk, cjk_space as _cjk_space_impl, lindera_available, lindera_error


def _normalize_engine_package(pkg: str) -> str:
    raw = (pkg or "").strip()
    if not raw:
        return raw
    if raw.startswith("sari-search"):
        # Backward-compat: sari-search -> sari
        suffix = raw[len("sari-search"):]
        return f"sari{suffix}"
    return raw


def _default_engine_package() -> str:
    env = (os.environ.get("SARI_ENGINE_PACKAGE") or "").strip()
    if env:
        return _normalize_engine_package(env)
    ver = ""
    try:
        from sari.version import __version__
        ver = __version__
    except Exception:
        ver = (os.environ.get("SARI_VERSION") or "").strip()
    if ver:
        parts = ver.split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"sari~={parts[0]}.{parts[1]}"
    return "sari"


ENGINE_PACKAGE = _normalize_engine_package(_default_engine_package())
_DEFAULT_ENGINE_MEM_MB = 512
_DEFAULT_ENGINE_INDEX_MEM_MB = 256
_DEFAULT_ENGINE_THREADS = 2

logger = logging.getLogger(__name__)


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


def _cjk_space(text: str) -> str:
    # Compatibility wrapper for tests/imports
    return _cjk_space_impl(text)


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
    tokenizer_ready: bool = True
    tokenizer_note: str = ""
    tokenizer_bundle_tag: str = ""
    tokenizer_bundle_path: str = ""
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
        self._auto_install = (os.environ.get("SARI_ENGINE_AUTO_INSTALL", "1").strip().lower() not in {"0", "false", "no", "off"})
        self._tantivy = None
        self._index = None
        self._schema = None
        self._fields: Dict[str, Any] = {}
        self._tokenizers_registered = False
        self._tokenizer_bundle_tag, self._tokenizer_bundle_path = self._find_tokenizer_bundle()

    @staticmethod
    def _platform_tokenizer_tag() -> str:
        plat = sys.platform
        arch = platform.machine().lower()
        if plat.startswith("darwin"):
            if arch in {"arm64", "aarch64"}:
                return "macosx_11_0_arm64"
            if arch in {"x86_64", "amd64"}:
                return "macosx_10_9_x86_64"
            return "macosx"
        if plat.startswith("win"):
            return "win_amd64"
        if plat.startswith("linux"):
            if arch in {"aarch64", "arm64"}:
                return "manylinux_2_17_aarch64"
            return "manylinux_2_17_x86_64"
        return "unknown"

    def _find_tokenizer_bundle(self) -> tuple[str, str]:
        try:
            base = Path(__file__).parent / "engine_tokenizer_data"
            tag = self._platform_tokenizer_tag()
            if not base.exists():
                return tag, ""
            # Find matching wheel for this platform tag
            for p in base.glob("lindera_python_ipadic-*.whl"):
                if tag in p.name:
                    return tag, str(p)
            return tag, ""
        except Exception:
            return "unknown", ""

    def _engine_limits(self) -> Tuple[int, int, int]:
        mem_mb = _env_int("SARI_ENGINE_MEM_MB", _DEFAULT_ENGINE_MEM_MB)
        index_mem_mb = _env_int("SARI_ENGINE_INDEX_MEM_MB", _DEFAULT_ENGINE_INDEX_MEM_MB)
        threads = _env_int("SARI_ENGINE_THREADS", _DEFAULT_ENGINE_THREADS)
        mem_mb = max(64, mem_mb)
        index_mem_mb = max(64, index_mem_mb)
        if index_mem_mb > (mem_mb // 2):
            index_mem_mb = max(64, mem_mb // 2)
        max_threads = max(1, os.cpu_count() or 1)
        if threads < 1:
            threads = 1
        max_threads = min(2, max_threads)
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
            "size_profile": (os.environ.get("SARI_SIZE_PROFILE") or "default").strip().lower(),
            "max_parse_bytes": int(os.environ.get("SARI_MAX_PARSE_BYTES", "0") or 0),
            "max_ast_bytes": int(os.environ.get("SARI_MAX_AST_BYTES", "0") or 0),
            "follow_symlinks": (os.environ.get("SARI_FOLLOW_SYMLINKS", "0").strip().lower() in ("1", "true", "yes", "on")),
            "engine_version": self._engine_version(),
            "max_doc_bytes": int(os.environ.get("SARI_ENGINE_MAX_DOC_BYTES", "4194304") or 4194304),
            "preview_bytes": int(os.environ.get("SARI_ENGINE_PREVIEW_BYTES", "8192") or 8192),
            "engine_tokenizer": (os.environ.get("SARI_ENGINE_TOKENIZER") or "auto").strip().lower(),
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

    def _register_tokenizers(self, index: Any) -> None:
        try:
            Tokenizer = self._tantivy.Tokenizer
            Filter = self._tantivy.Filter
            TextAnalyzerBuilder = self._tantivy.TextAnalyzerBuilder
        except Exception:
            return

        try:
            latin = (
                TextAnalyzerBuilder(Tokenizer.regex(r"[A-Za-z0-9_]+"))
                .filter(Filter.lowercase())
                .build()
            )
            # Mixed analyzer: CJK single-char tokens + latin words
            cjk = (
                TextAnalyzerBuilder(Tokenizer.regex(r"[\u4E00-\u9FFF]|[\u3400-\u4DBF]|[\u3040-\u30FF]|[A-Za-z0-9_]+"))
                .filter(Filter.lowercase())
                .build()
            )
            index.register_tokenizer("tokenizer_latin", latin)
            index.register_tokenizer("tokenizer_cjk", cjk)
            self._tokenizers_registered = True
        except Exception:
            logger.warning("tokenizer registration failed; using default tantivy tokenizer")
            return

    def _resolve_body_tokenizer(self) -> str:
        mode = (os.environ.get("SARI_ENGINE_TOKENIZER") or "auto").strip().lower()
        if mode == "latin":
            return "tokenizer_latin"
        if mode == "cjk":
            return "tokenizer_cjk"
        return "tokenizer_cjk"

    def _ensure_index(self) -> None:
        self._tantivy = _load_tantivy(self._venv_dir, self._auto_install)
        if self._schema and self._index:
            return
        schema_builder = self._tantivy.SchemaBuilder()
        body_tokenizer = self._resolve_body_tokenizer()
        def _add_text(name: str, stored: bool = False, tokenizer_name: Optional[str] = None):
            if tokenizer_name:
                try:
                    return schema_builder.add_text_field(name, stored=stored, tokenizer_name=tokenizer_name)
                except TypeError:
                    pass
            return schema_builder.add_text_field(name, stored=stored)
        self._fields = {
            "doc_id": _add_text("doc_id", stored=True),
            "path": _add_text("path", stored=True),
            "repo": _add_text("repo", stored=True),
            "root_id": _add_text("root_id", stored=True),
            "rel_path": _add_text("rel_path", stored=True),
            "path_text": _add_text("path_text", tokenizer_name="tokenizer_latin"),
            "body_text": _add_text("body_text", tokenizer_name=body_tokenizer),
            "preview": _add_text("preview", stored=True),
            "mtime": schema_builder.add_i64_field("mtime", stored=True),
            "size": schema_builder.add_i64_field("size", stored=True),
        }
        self._schema = schema_builder.build()
        if self._index_dir.exists() and (self._index_dir / "meta.json").exists():
            self._index = self._tantivy.Index(self._index_dir.as_posix())
        else:
            self._index_dir.mkdir(parents=True, exist_ok=True)
            self._index = self._tantivy.Index(self._schema, self._index_dir.as_posix())
        self._register_tokenizers(self._index)

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
                tokenizer_ready=self._tokenizers_registered,
                tokenizer_note="tokenizers not registered" if not self._tokenizers_registered else "",
                tokenizer_bundle_tag=self._tokenizer_bundle_tag,
                tokenizer_bundle_path=self._tokenizer_bundle_path,
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
            tokenizer_ready=self._tokenizers_registered,
            tokenizer_note="tokenizers not registered" if not self._tokenizers_registered else "",
            tokenizer_bundle_tag=self._tokenizer_bundle_tag,
            tokenizer_bundle_path=self._tokenizer_bundle_path,
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
        if _has_cjk(norm_q):
            norm_q = _cjk_space(norm_q)
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
        getter = getattr(self._db, "get_read_connection", None)
        conn = getter() if callable(getter) else self._db._read
        rows = conn.execute(sql, (f"%{like_q}%", limit)).fetchall()
        out = []
        for r in rows:
            repo, c = str(r["repo"]), int(r["c"])
            out.append({"repo": repo, "score": c, "evidence": ""})
        return out


def _path_pattern_match(path: str, pattern: str) -> bool:
    import fnmatch
    p = path.replace("\\", "/")
    if p.startswith("root-") and "/" in p:
        p = p.split("/", 1)[1]
    p = p.lstrip("/")
    pat = pattern.replace("\\", "/")
    if pat.startswith("root-") and "/" in pat:
        pat = pat.split("/", 1)[1]
    if pat.startswith("/"):
        pat = pat.lstrip("/")
    if p.endswith("/" + pat) or p == pat:
        return True
    return fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, f"*/{pat}") or fnmatch.fnmatch(p, f"*/{pat}/*")


def _exclude_pattern_match(path: str, patterns: List[str]) -> bool:
    import fnmatch
    p = path.replace("\\", "/")
    if p.startswith("root-") and "/" in p:
        p = p.split("/", 1)[1]
    p = p.lstrip("/")
    for ptn in patterns:
        pat = str(ptn).replace("\\", "/")
        if pat.startswith("root-") and "/" in pat:
            pat = pat.split("/", 1)[1]
        if pat.startswith("/"):
            pat = pat.lstrip("/")
        if pat in p or fnmatch.fnmatch(p, f"*{pat}*"):
            return True
    return False
