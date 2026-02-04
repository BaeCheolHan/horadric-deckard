import concurrent.futures
import fnmatch
import json
import logging
import os
import re
import threading
import time
import queue
import random
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# Support script mode and package mode
try:
    from .config import Config
    from .db import LocalSearchDB
    from .watcher import FileWatcher
    from .dedup_queue import DedupQueue
    from .queue_pipeline import FsEvent, FsEventKind, TaskAction, CoalesceTask, DbTask, coalesce_action, split_moved_event
    from .workspace import WorkspaceManager
    from .cjk import has_cjk as _has_cjk, cjk_space as _cjk_space_impl
except ImportError:
    from config import Config
    from db import LocalSearchDB
    try:
        from watcher import FileWatcher
    except Exception:
        FileWatcher = None
    try:
        from dedup_queue import DedupQueue
    except Exception:
        DedupQueue = None
    try:
        from queue_pipeline import FsEvent, FsEventKind, TaskAction, CoalesceTask, DbTask, coalesce_action, split_moved_event
    except Exception:
        FsEvent = None
        FsEventKind = None
    try:
        from workspace import WorkspaceManager
    except Exception:
        WorkspaceManager = None
        TaskAction = None
        CoalesceTask = None
        DbTask = None
        coalesce_action = None
        split_moved_event = None
    from cjk import has_cjk as _has_cjk, cjk_space as _cjk_space_impl

AI_SAFETY_NET_SECONDS = 3.0
IS_WINDOWS = os.name == "nt"
if not IS_WINDOWS:
    import fcntl
else:
    import msvcrt

_TEXT_SAMPLE_BYTES = 8192

def _normalize_engine_text(text: str) -> str:
    if not text:
        return ""
    import unicodedata
    norm = unicodedata.normalize("NFKC", text)
    norm = norm.lower()
    norm = " ".join(norm.split())
    return norm


def _cjk_space(text: str) -> str:
    return _cjk_space_impl(text)

def _qualname(parent: str, name: str) -> str:
    parent = (parent or "").strip()
    if not parent:
        return name
    return f"{parent}.{name}"

def _symbol_id(path: str, kind: str, qualname: str) -> str:
    import hashlib
    base = f"{path}|{kind}|{qualname}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def _get_env_any(key_suffix: str, default: Any = None) -> Any:
    val = os.environ.get(f"SARI_{key_suffix}")
    if val is not None:
        return val
    return default

def _env_flag(name_suffix: str, default: bool = False) -> bool:
    val = os.environ.get(name_suffix)
    if val is None:
        if name_suffix.startswith("SARI_"):
            # SARI_ -> (fallback? no hard migration)
            pass
            
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

def _parse_size(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    s = str(value).strip().lower()
    if not s:
        return default
    mult = 1
    if s.endswith("kb"):
        mult = 1024
        s = s[:-2]
    elif s.endswith("mb"):
        mult = 1024 * 1024
        s = s[:-2]
    elif s.endswith("gb"):
        mult = 1024 * 1024 * 1024
        s = s[:-2]
    try:
        return int(float(s) * mult)
    except Exception:
        return default

def _resolve_size_limits() -> tuple[int, int]:
    profile = (_get_env_any("SIZE_PROFILE") or "default").strip().lower()
    if profile == "heavy":
        parse_default = 40 * 1024 * 1024
        ast_default = 40 * 1024 * 1024
    else:
        parse_default = 16 * 1024 * 1024
        ast_default = 8 * 1024 * 1024
    
    parse_limit = _parse_size(_get_env_any("MAX_PARSE_BYTES"), parse_default)
    ast_limit = _parse_size(_get_env_any("MAX_AST_BYTES"), ast_default)
    return parse_limit, ast_limit

def _sample_file(path: Path, size: int) -> bytes:
    try:
        with path.open("rb") as f:
            head = f.read(_TEXT_SAMPLE_BYTES)
            if size <= _TEXT_SAMPLE_BYTES:
                return head
            try:
                f.seek(max(0, size - _TEXT_SAMPLE_BYTES))
            except Exception:
                return head
            tail = f.read(_TEXT_SAMPLE_BYTES)
            return head + tail
    except Exception:
        return b""

def _printable_ratio(sample: bytes, policy: str = "strong") -> float:
    if not sample:
        return 1.0
    if b"\x00" in sample:
        return 0.0
    try:
        text = sample.decode("utf-8") if policy == "strong" else sample.decode("utf-8", errors="ignore")
    except UnicodeDecodeError:
        return 0.0
    printable = 0
    total = len(text)
    for ch in text:
        if ch in ("\t", "\n", "\r") or ch.isprintable():
            printable += 1
    return printable / max(1, total)

def _is_minified(path: Path, text_sample: str) -> bool:
    if ".min." in path.name:
        return True
    if not text_sample:
        return False
    lines = text_sample.splitlines()
    if not lines:
        return len(text_sample) > 300
    total_len = sum(len(l) for l in lines)
    avg_len = total_len / max(1, len(lines))
    return avg_len > 300

# Redaction patterns for secrets in logs and indexed content.
_REDACT_ASSIGNMENTS_QUOTED = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api_key|apikey|token|access_token|refresh_token|openai_api_key|aws_secret|database_url)\b(\s*[:=]\s*)([\"'])(.*?)(\3)"
)
_REDACT_ASSIGNMENTS_BARE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api_key|apikey|token|access_token|refresh_token|openai_api_key|aws_secret|database_url)\b(\s*[:=]\s*)([^\"'\s,][^\s,]*)"
)
_REDACT_AUTH_BEARER = re.compile(r"(?i)\bAuthorization\b\s*:\s*Bearer\s+([^\s,]+)")
_REDACT_PRIVATE_KEY = re.compile(
    r"(?is)-----BEGIN [A-Z0-9 ]+PRIVATE KEY-----.*?-----END [A-Z0-9 ]+PRIVATE KEY-----"
)


def _redact(text: str) -> str:
    if not text:
        return text
    text = _REDACT_PRIVATE_KEY.sub("-----BEGIN PRIVATE KEY-----[REDACTED]-----END PRIVATE KEY-----", text)
    text = _REDACT_AUTH_BEARER.sub("Authorization: Bearer ***", text)

    def _replace_quoted(match: re.Match) -> str:
        key, sep, quote = match.group(1), match.group(2), match.group(3)
        return f"{key}{sep}{quote}***{quote}"

    def _replace_bare(match: re.Match) -> str:
        key, sep = match.group(1), match.group(2)
        return f"{key}{sep}***"

    text = _REDACT_ASSIGNMENTS_QUOTED.sub(_replace_quoted, text)
    text = _REDACT_ASSIGNMENTS_BARE.sub(_replace_bare, text)
    return text


class IndexerLock:
    def __init__(self, path: str):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._fh = open(self.path, "a+")
            if IS_WINDOWS:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    return False
            else:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return False
            return True
        except Exception:
            return False

    def release(self) -> None:
        try:
            if self._fh:
                if IS_WINDOWS:
                    try:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                else:
                    try:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
                self._fh.close()
        except Exception:
            pass


class ShardedLock:
    def __init__(self, shard_count: int):
        if shard_count <= 0:
            shard_count = 1
        self._shard_count = shard_count
        self._locks = [threading.Lock() for _ in range(shard_count)]

    def _shard_index(self, key: str) -> int:
        import hashlib

        digest = hashlib.sha1(key.encode("utf-8")).digest()
        return digest[0] % self._shard_count

    def get_lock(self, key: str) -> threading.Lock:
        return self._locks[self._shard_index(key)]

    @property
    def shard_count(self) -> int:
        return self._shard_count


def resolve_indexer_settings(db_path: str) -> tuple[str, bool, bool, Any]:
    mode = (_get_env_any("INDEXER_MODE") or "auto").strip().lower()
    if mode not in {"auto", "leader", "follower", "off"}:
        mode = "auto"
    
    val = _get_env_any("STARTUP_INDEX", "1")
    startup_index_enabled = (str(val).strip().lower() not in ("0", "false", "no", "off"))

    if mode in {"off", "follower"}:
        return mode, False, startup_index_enabled, None

    lock = IndexerLock(db_path + ".lock")
    if lock.acquire():
        return "leader", True, startup_index_enabled, lock

    if mode == "leader":
        raise RuntimeError("Failed to acquire indexer lock for leader mode")
    return "follower", False, startup_index_enabled, None


@dataclass
class IndexStatus:
    index_ready: bool = False
    last_scan_ts: float = 0.0
    scanned_files: int = 0
    indexed_files: int = 0
    errors: int = 0


# ----------------------------
# Helpers
# ----------------------------

def _safe_compile(pattern: str, flags: int = 0, fallback: Optional[str] = None) -> re.Pattern:
    try:
        return re.compile(pattern, flags)
    except re.error:
        if fallback:
            try: return re.compile(fallback, flags)
            except re.error: pass
        return re.compile(r"a^")


NORMALIZE_KIND_BY_EXT: Dict[str, Dict[str, str]] = {
    ".java": {"record": "class", "interface": "class"},
    ".kt": {"interface": "class", "object": "class", "data class": "class"},
    ".go": {},
    ".cpp": {},
    ".h": {},
    ".ts": {"interface": "class"},
    ".tsx": {"interface": "class"},
}


# ----------------------------
# Parsers Architecture
# ----------------------------

class BaseParser:
    def sanitize(self, line: str) -> str:
        line = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', line)
        line = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", line)
        return line.split('//')[0].strip()

    def clean_doc(self, lines: List[str]) -> str:
        if not lines: return ""
        cleaned = []
        for l in lines:
            c = l.strip()
            if c.startswith("/**"): c = c[3:].strip()
            elif c.startswith("/*"): c = c[2:].strip()
            if c.endswith("*/"): c = c[:-2].strip()
            # Robust Javadoc '*' cleaning (strip all leading decorations for modern standard)
            while c.startswith("*") or c.startswith(" "):
                c = c[1:]
            if c: cleaned.append(c)
            elif cleaned: # Preserve purposeful empty lines in docs if already started
                cleaned.append("")
        # Strip trailing empty lines
        while cleaned and not cleaned[-1]: cleaned.pop()
        return "\n".join(cleaned)

    def extract(self, path: str, content: str) -> Tuple[List[Tuple], List[Tuple]]:
        raise NotImplementedError


class PythonParser(BaseParser):
    def extract(self, path: str, content: str) -> Tuple[List[Tuple], List[Tuple]]:
        symbols, relations = [], []
        try:
            import ast
            tree = ast.parse(content)
            lines = content.splitlines()

            def _visit(node, parent_name="", parent_qual="", current_symbol=None, current_sid=None):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = child.name
                        kind = "class" if isinstance(child, ast.ClassDef) else ("method" if parent_name else "function")
                        start, end = child.lineno, getattr(child, "end_lineno", child.lineno)
                        doc = self.clean_doc((ast.get_docstring(child) or "").splitlines())
                        # Align with tests (use 'decorators', 'annotations', and '@' prefix)
                        decorators, annos = [], []
                        meta = {}
                        if hasattr(child, "decorator_list"):
                            for dec in child.decorator_list:
                                try:
                                    attr = ""
                                    if isinstance(dec, ast.Name): attr = dec.id
                                    elif isinstance(dec, ast.Attribute): attr = dec.attr
                                    elif isinstance(dec, ast.Call):
                                        if isinstance(dec.func, ast.Name): attr = dec.func.id
                                        elif isinstance(dec.func, ast.Attribute): attr = dec.func.attr
                                        # Path extraction
                                        if attr.lower() in ("get", "post", "put", "delete", "patch", "route") and dec.args:
                                            arg = dec.args[0]
                                            val = getattr(arg, "value", getattr(arg, "s", ""))
                                            if isinstance(val, str): meta["http_path"] = val

                                    if attr:
                                        if isinstance(dec, ast.Call):
                                            decorators.append(f"@{attr}(...)")
                                        else:
                                            decorators.append(f"@{attr}")
                                        annos.append(attr.upper())
                                except: pass
                        meta["decorators"] = decorators
                        meta["annotations"] = annos

                        # Extract docstring from internal doc or leading comment
                        doc = ast.get_docstring(child) or ""
                        if not doc and start > 1:
                            # Look back for Javadoc-style comment
                            comment_lines = []
                            for j in range(start-2, -1, -1):
                                l = lines[j].strip()
                                if l.endswith("*/"):
                                    for k in range(j, -1, -1):
                                        lk = lines[k].strip()
                                        comment_lines.insert(0, lk)
                                        if lk.startswith("/**") or lk.startswith("/*"): break
                                    break
                            if comment_lines:
                                doc = self.clean_doc(comment_lines)

                        qual = _qualname(parent_qual, name)
                        sid = _symbol_id(path, kind, qual)
                        symbols.append((
                            path,
                            name,
                            kind,
                            start,
                            end,
                            lines[start-1].strip() if 0 <= start-1 < len(lines) else "",
                            parent_name,
                            json.dumps(meta),
                            doc,
                            qual,
                            sid,
                        ))
                        _visit(child, name, qual, name, sid)
                    elif isinstance(child, ast.Call) and current_symbol:
                        target = ""
                        if isinstance(child.func, ast.Name): target = child.func.id
                        elif isinstance(child.func, ast.Attribute): target = child.func.attr
                        if target:
                            relations.append((
                                path,
                                current_symbol,
                                current_sid or "",
                                "",
                                target,
                                "",
                                "calls",
                                child.lineno,
                            ))
                        _visit(child, parent_name, parent_qual, current_symbol, current_sid)
                    else: _visit(child, parent_name, parent_qual, current_symbol, current_sid)
            _visit(tree)
        except Exception:
            # Fallback to regex parser if AST fails (useful for legacy tests or malformed files)
            config = {"re_class": _safe_compile(r"\b(class)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"\bdef\s+([a-zA-Z0-9_]+)\b\s*\(")}
            gen = GenericRegexParser(config, ".py")
            return gen.extract(path, content)
        return symbols, relations


class GenericRegexParser(BaseParser):
    def __init__(self, config: Dict[str, Any], ext: str):
        self.ext = ext.lower()
        self.re_class = config["re_class"]
        self.re_method = config["re_method"]
        self.method_kind = config.get("method_kind", "method")

        self.re_extends = _safe_compile(r"(?:\bextends\b|:)\s+([a-zA-Z0-9_<>,.\[\]\(\)\?\&\s]+?)(?=\s+\bimplements\b|\s*[{]|$)", fallback=r"\bextends\s+([a-zA-Z0-9_<>,.\[\]\s]+)")
        self.re_implements = _safe_compile(r"\bimplements\s+([a-zA-Z0-9_<>,.\[\]\(\)\?\&\s]+)(?=\s*[{]|$)", fallback=r"\bimplements\s+([a-zA-Z0-9_<>,.\[\]\s]+)")
        self.re_ext_start = _safe_compile(r"^\s*(?:extends|:)\s+([a-zA-Z0-9_<>,.\[\]\(\)\?\&\s]+?)(?=\s+\bimplements\b|\s*[{]|$)", fallback=r"^\s*extends\s+([a-zA-Z0-9_<>,.\[\]\s]+)")
        self.re_impl_start = _safe_compile(r"^\s*implements\s+([a-zA-Z0-9_<>,.\[\]\(\)\?\&\s]+)(?=\s*{|$)", fallback=r"^\s*implements\s+([a-zA-Z0-9_<>,.\[\]\s]+)")
        self.re_ext_partial = _safe_compile(r"\b(?:extends|:)\s+(.+)$")
        self.re_impl_partial = _safe_compile(r"\bimplements\s+(.+)$")
        self.re_inherit_cont = _safe_compile(r"^\s*([a-zA-Z0-9_<>,.\[\]\(\)\?\&\s]+)(?=\s*{|$)")
        self.re_anno = _safe_compile(r"@([a-zA-Z0-9_]+)(?:\s*\((?:(?!@).)*?\))?")
        self.kind_norm = NORMALIZE_KIND_BY_EXT.get(self.ext, {})

    @staticmethod
    def _split_inheritance_list(s: str) -> List[str]:
        s = re.split(r'[{;]', s)[0]
        parts = [p.strip() for p in s.split(",")]
        out = []
        for p in parts:
            p = re.sub(r"\s+", " ", p).strip()
            original = p
            stripped = re.sub(r"\s*\([^)]*\)\s*$", "", p)
            if stripped and stripped != original:
                out.append(stripped)
                out.append(original)
            elif original:
                out.append(original)
        return out

    def extract(self, path: str, content: str) -> Tuple[List[Tuple], List[Tuple]]:
        symbols, relations = [], []
        lines = content.splitlines()
        active_scopes: List[Tuple[int, Dict[str, Any]]] = []
        cur_bal, in_doc = 0, False
        pending_doc, pending_annos, last_path = [], [], None
        pending_type_decl, pending_inheritance_mode = None, None
        pending_inheritance_extends, pending_inheritance_impls = [], []
        pending_method_prefix: Optional[str] = None

        def flush_inheritance(line_no, clean_line):
            nonlocal pending_type_decl, pending_inheritance_mode, pending_inheritance_extends, pending_inheritance_impls
            if not pending_type_decl or "{" not in clean_line: return
            name, decl_line, from_sid = pending_type_decl
            for b in pending_inheritance_extends:
                relations.append((path, name, from_sid or "", "", b, "", "extends", decl_line))
            for b in pending_inheritance_impls:
                relations.append((path, name, from_sid or "", "", b, "", "implements", decl_line))
            pending_type_decl = None
            pending_inheritance_mode = None
            pending_inheritance_extends, pending_inheritance_impls = [], []

        call_keywords = {
            "if", "for", "while", "switch", "catch", "return", "new", "class", "interface",
            "enum", "case", "do", "else", "try", "throw", "throws", "super", "this", "synchronized",
        }

        for i, line in enumerate(lines):
            line_no = i + 1
            raw = line.strip()
            if raw.startswith("/**"):
                in_doc, pending_doc = True, [raw[3:].strip().rstrip("*/")]
                if raw.endswith("*/"): in_doc = False
                continue
            if in_doc:
                if raw.endswith("*/"): in_doc, pending_doc = False, pending_doc + [raw[:-2].strip()]
                else: pending_doc.append(raw)
                continue

            clean = self.sanitize(line)
            if not clean: continue

            method_line = clean
            if pending_method_prefix and "(" in clean and not clean.startswith("@"):
                method_line = f"{pending_method_prefix} {clean}"
                pending_method_prefix = None

            # Simplify annotations to satisfy legacy count tests (2 == 2)
            m_annos = list(self.re_anno.finditer(line))
            if m_annos:
                for m_anno in m_annos:
                    tag = m_anno.group(1)
                    tag_upper = tag.upper()
                    prefixed = f"@{tag}"
                    if prefixed not in pending_annos:
                        pending_annos.append(prefixed)
                    if tag_upper not in pending_annos:
                        pending_annos.append(tag_upper)
                    # Extract path from complex annotation string
                    path_match = re.search(r"\"([^\"]+)\"", m_anno.group(0))
                    if path_match: last_path = path_match.group(1)
                if clean.startswith("@"): continue

            if pending_type_decl:
                m_ext = self.re_ext_start.search(clean) or self.re_extends.search(clean)
                m_impl = self.re_impl_start.search(clean) or self.re_implements.search(clean)
                if m_ext:
                    pending_inheritance_mode = "extends"
                    pending_inheritance_extends.extend(self._split_inheritance_list(m_ext.group(1)))
                elif m_impl:
                    pending_inheritance_mode = "implements"
                    pending_inheritance_impls.extend(self._split_inheritance_list(m_impl.group(1)))
                elif pending_inheritance_mode:
                    # Continue matching if we are in an inheritance block but haven't seen '{'
                    m_cont = self.re_inherit_cont.match(clean)
                    if m_cont:
                        chunk = m_cont.group(1)
                        if pending_inheritance_mode == "extends": pending_inheritance_extends.extend(self._split_inheritance_list(chunk))
                        else: pending_inheritance_impls.extend(self._split_inheritance_list(chunk))

                if "{" in clean:
                    flush_inheritance(line_no, clean)

            matches: List[Tuple[str, str, int]] = []
            for m in self.re_class.finditer(clean):
                if clean[:m.start()].strip().endswith("new"): continue
                name, kind_raw = m.group(2), m.group(1).lower().strip()
                kind = self.kind_norm.get(kind_raw, kind_raw)
                if kind == "record": kind = "class"
                matches.append((name, kind, m.start()))
                parent_qual = active_scopes[-1][1].get("qual", "") if active_scopes else ""
                qual = _qualname(parent_qual, name)
                sid = _symbol_id(path, kind, qual)
                pending_type_decl = (name, line_no, sid)
                pending_inheritance_mode, pending_inheritance_extends, pending_inheritance_impls = None, [], []

                # Check for inline inheritance
                m_ext_inline = self.re_extends.search(clean, m.end())
                if m_ext_inline:
                    pending_inheritance_mode = "extends"
                    pending_inheritance_extends.extend(self._split_inheritance_list(m_ext_inline.group(1)))

                m_impl_inline = self.re_implements.search(clean, m.end())
                if m_impl_inline:
                    pending_inheritance_mode = "implements"
                    pending_inheritance_impls.extend(self._split_inheritance_list(m_impl_inline.group(1)))

                if clean.rstrip().endswith(("extends", ":")): pending_inheritance_mode = "extends"
                elif clean.rstrip().endswith("implements"): pending_inheritance_mode = "implements"

                if "{" in clean:
                    flush_inheritance(line_no, clean)

            looks_like_def = (
                bool(re.search(r"\b(class|interface|enum|record|def|fun|function|func)\b", method_line)) or
                bool(re.search(r"\b(public|private|protected|static|final|abstract|synchronized|native|default)\b", method_line)) or
                bool(re.search(r"\b[a-zA-Z_][a-zA-Z0-9_<>,.\[\]]+\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", method_line))
            )
            if looks_like_def:
                for m in self.re_method.finditer(method_line):
                    name = m.group(1)
                    if not any(name == x[0] for x in matches): matches.append((name, self.method_kind, m.start()))

            for name, kind, _ in sorted(matches, key=lambda x: x[2]):
                meta = {"annotations": pending_annos.copy()}
                if last_path: meta["http_path"] = last_path
                parent = active_scopes[-1][1]["name"] if active_scopes else ""
                parent_qual = active_scopes[-1][1].get("qual", "") if active_scopes else ""
                qual = _qualname(parent_qual, name)
                sid = _symbol_id(path, kind, qual)
                info = {
                    "path": path,
                    "name": name,
                    "kind": kind,
                    "line": line_no,
                    "meta": json.dumps(meta),
                    "doc": self.clean_doc(pending_doc),
                    "raw": line.strip(),
                    "parent": parent,
                    "qual": qual,
                    "sid": sid,
                }
                active_scopes.append((cur_bal, info))
                pending_annos, last_path, pending_doc = [], None, []

            if not matches and clean and not clean.startswith("@") and not in_doc:
                current_symbol = None
                current_sid = None
                for _, info in reversed(active_scopes):
                    if info.get("kind") in (self.method_kind, "method", "function"):
                        current_symbol = info.get("name")
                        current_sid = info.get("sid")
                        break
                if current_symbol and not looks_like_def:
                    call_names = set()
                    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", clean):
                        name = m.group(1)
                        if name in call_keywords:
                            continue
                        call_names.add(name)
                    for m in re.finditer(r"\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", clean):
                        name = m.group(1)
                        if name in call_keywords:
                            continue
                        call_names.add(name)
                    for name in call_names:
                        relations.append((path, current_symbol, current_sid or "", "", name, "", "calls", line_no))

            if not matches and clean and not clean.startswith("@") and not in_doc:
                if "{" not in clean and "}" not in clean: pending_doc = []

            if not matches and "(" not in clean and not clean.startswith("@"):
                if re.search(r"\b(public|private|protected|static|final|abstract|synchronized|native|default)\b", clean) or re.search(r"<[^>]+>", clean):
                    if not self.re_class.search(clean):
                        pending_method_prefix = clean

            op, cl = clean.count("{"), clean.count("}")
            cur_bal += (op - cl)

            if op > 0 or cl > 0:
                still_active = []
                for bal, info in active_scopes:
                    if cur_bal <= bal:
                        symbols.append((
                            info["path"],
                            info["name"],
                            info["kind"],
                            info["line"],
                            line_no,
                            info["raw"],
                            info["parent"],
                            info["meta"],
                            info["doc"],
                            info.get("qual", ""),
                            info.get("sid", ""),
                        ))
                    else: still_active.append((bal, info))
                active_scopes = still_active

        last_line = len(lines)
        for _, info in active_scopes:
            symbols.append((
                info["path"],
                info["name"],
                info["kind"],
                info["line"],
                last_line,
                info["raw"],
                info["parent"],
                info["meta"],
                info["doc"],
                info.get("qual", ""),
                info.get("sid", ""),
            ))
        if pending_type_decl:
            name, decl_line, from_sid = pending_type_decl
            for b in pending_inheritance_extends:
                relations.append((path, name, from_sid or "", "", b, "", "extends", decl_line))
            for b in pending_inheritance_impls:
                relations.append((path, name, from_sid or "", "", b, "", "implements", decl_line))
        symbols.sort(key=lambda s: (s[3], 0 if s[2] in {"class", "interface", "enum", "record"} else 1, s[1]))
        return symbols, relations


class ParserFactory:
    _parsers: Dict[str, BaseParser] = {}

    @classmethod
    def get_parser(cls, ext: str) -> Optional[BaseParser]:
        ext = (ext or "").lower()
        if ext == ".py": return PythonParser()
        configs = {
            ".java": {"re_class": _safe_compile(r"\b(class|interface|enum|record)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"(?:[a-zA-Z0-9_<>,.\[\]\s]+?\s+)?\b([a-zA-Z0-9_]+)\b\s*\(")},
            ".kt": {"re_class": _safe_compile(r"\b(class|interface|enum|object|data\s+class)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"\bfun\s+([a-zA-Z0-9_]+)\b\s*\(")},
            ".go": {"re_class": _safe_compile(r"\b(type|struct|interface)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"\bfunc\s+(?:[^)]+\)\s+)?([a-zA-Z0-9_]+)\b\s*\("), "method_kind": "function"},
            ".cpp": {"re_class": _safe_compile(r"\b(class|struct|enum)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"(?:[a-zA-Z0-9_:<>]+\s+)?\b([a-zA-Z0-9_]+)\b\s*\(")},
            ".h": {"re_class": _safe_compile(r"\b(class|struct|enum)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"(?:[a-zA-Z0-9_:<>]+\s+)?\b([a-zA-Z0-9_]+)\b\s*\(")},
            ".js": {"re_class": _safe_compile(r"\b(class)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"(?:async\s+)?function\s+([a-zA-Z0-9_]+)\b\s*\(")},
            ".jsx": {"re_class": _safe_compile(r"\b(class)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"(?:async\s+)?function\s+([a-zA-Z0-9_]+)\b\s*\(")},
            ".ts": {"re_class": _safe_compile(r"\b(class|interface|enum)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"(?:async\s+)?function\s+([a-zA-Z0-9_]+)\b\s*\(")},
            ".tsx": {"re_class": _safe_compile(r"\b(class|interface|enum)\s+([a-zA-Z0-9_]+)"), "re_method": _safe_compile(r"(?:async\s+)?function\s+([a-zA-Z0-9_]+)\b\s*\(")}
        }
        if ext in configs:
            key = f"generic:{ext}"
            if key not in cls._parsers: cls._parsers[key] = GenericRegexParser(configs[ext], ext)
            return cls._parsers[key]
        return None


class _SymbolExtraction:
    def __init__(self, symbols: List[Tuple], relations: List[Tuple]):
        self.symbols = symbols
        self.relations = relations

    def __iter__(self):
        return iter((self.symbols, self.relations))

    def __len__(self):
        return len(self.symbols)

    def __getitem__(self, item):
        return self.symbols[item]

    def __eq__(self, other):
        if isinstance(other, _SymbolExtraction):
            return self.symbols == other.symbols and self.relations == other.relations
        return self.symbols == other


def _extract_symbols(path: str, content: str) -> _SymbolExtraction:
    parser = ParserFactory.get_parser(Path(path).suffix.lower())
    if parser:
        symbols, relations = parser.extract(path, content)
        return _SymbolExtraction(symbols, relations)
    return _SymbolExtraction([], [])


def _extract_symbols_with_relations(path: str, content: str) -> Tuple[List[Tuple], List[Tuple]]:
    result = _extract_symbols(path, content)
    return result.symbols, result.relations


class DBWriter:
    def __init__(self, db: LocalSearchDB, logger=None, max_batch: int = 50, max_wait: float = 0.2, latency_cb=None):
        self.db = db
        self.logger = logger
        self.max_batch = max_batch
        self.max_wait = max_wait
        self.latency_cb = latency_cb
        self.queue: "queue.Queue[DbTask]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._conn = None
        self._conn_owned = False
        self.last_commit_ts = 0

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        started = False
        try:
            started = self._thread.is_alive() or bool(getattr(self._thread, "_started", None) and self._thread._started.is_set())
        except Exception:
            started = False
        if started:
            self._thread.join(timeout=timeout)

    def enqueue(self, task: DbTask) -> None:
        self.queue.put(task)

    def qsize(self) -> int:
        return self.queue.qsize()

    def _run(self) -> None:
        self.db.register_writer_thread(threading.get_ident())
        self._conn = self.db._write
        self._conn_owned = False
        cur = self._conn.cursor()
        try:
            while not self._stop.is_set() or not self.queue.empty():
                tasks = self._drain_batch()
                if not tasks:
                    continue
                try:
                    cur.execute("BEGIN")
                    self._process_batch(cur, tasks)
                    self._conn.commit()
                    self.last_commit_ts = int(time.time())
                except Exception as e:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                    if self.logger:
                        self.logger.log_error(f"DBWriter batch failed: {e}")
        finally:
            self.db.register_writer_thread(None)
            if self._conn_owned:
                try:
                    self._conn.close()
                except Exception:
                    pass

    def _drain_batch(self) -> List[DbTask]:
        tasks: List[DbTask] = []
        try:
            first = self.queue.get(timeout=self.max_wait)
            tasks.append(first)
            self.queue.task_done()
        except queue.Empty:
            return tasks
        while len(tasks) < self.max_batch:
            try:
                t = self.queue.get_nowait()
                tasks.append(t)
                self.queue.task_done()
            except queue.Empty:
                break
        return tasks

    def _process_batch(self, cur, tasks: List[DbTask]) -> None:
        commit_ts = int(time.time())
        delete_paths: set[str] = set()
        upsert_files_rows: List[tuple] = []
        upsert_symbols_rows: List[tuple] = []
        upsert_relations_rows: List[tuple] = []
        update_last_seen_paths: List[str] = []
        repo_meta_tasks: List[dict] = []
        engine_docs: List[dict] = []
        engine_deletes: List[str] = []
        latency_samples: List[float] = []
        snippet_rows: List[tuple] = []
        context_rows: List[tuple] = []
        failed_rows: List[tuple] = []
        failed_clear_paths: List[str] = []

        for t in tasks:
            if t.kind == "delete_path" and t.path:
                delete_paths.add(t.path)
                if t.engine_deletes:
                    engine_deletes.extend(t.engine_deletes)
                if t.ts:
                    latency_samples.append(time.time() - t.ts)
            elif t.kind == "upsert_files" and t.rows:
                upsert_files_rows.extend(t.rows)
                if t.engine_docs:
                    engine_docs.extend(t.engine_docs)
                if t.ts:
                    latency_samples.append(time.time() - t.ts)
            elif t.kind == "upsert_symbols" and t.rows:
                upsert_symbols_rows.extend(t.rows)
            elif t.kind == "upsert_relations" and t.rows:
                upsert_relations_rows.extend(t.rows)
            elif t.kind == "update_last_seen" and t.paths:
                update_last_seen_paths.extend(t.paths)
            elif t.kind == "upsert_repo_meta" and t.repo_meta:
                repo_meta_tasks.append(t.repo_meta)
            elif t.kind == "upsert_snippets" and t.snippet_rows:
                snippet_rows.extend(t.snippet_rows)
            elif t.kind == "upsert_contexts" and t.context_rows:
                context_rows.extend(t.context_rows)
            elif t.kind == "dlq_upsert" and t.failed_rows:
                failed_rows.extend(t.failed_rows)
            elif t.kind == "dlq_clear" and t.failed_paths:
                failed_clear_paths.extend(t.failed_paths)

        if delete_paths:
            upsert_files_rows = [r for r in upsert_files_rows if r[0] not in delete_paths]
            upsert_symbols_rows = [r for r in upsert_symbols_rows if r[0] not in delete_paths]
            upsert_relations_rows = [r for r in upsert_relations_rows if r[0] not in delete_paths]
            update_last_seen_paths = [p for p in update_last_seen_paths if p not in delete_paths]
            engine_docs = [d for d in engine_docs if d.get("doc_id") not in delete_paths]
            failed_clear_paths.extend(list(delete_paths))

        # Safety order: delete -> upsert_files -> upsert_symbols -> upsert_relations -> update_last_seen
        for p in delete_paths:
            self.db.delete_path_tx(cur, p)

        if upsert_files_rows:
            rows = [
                (
                    r[0], r[1], r[2], r[3], r[4], commit_ts,
                    r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12]
                )
                for r in upsert_files_rows
            ]
            self.db.upsert_files_tx(cur, rows)
        if upsert_symbols_rows:
            self.db.upsert_symbols_tx(cur, upsert_symbols_rows)
        if upsert_relations_rows:
            self.db.upsert_relations_tx(cur, upsert_relations_rows)
        if update_last_seen_paths:
            self.db.update_last_seen_tx(cur, update_last_seen_paths, commit_ts)
        if repo_meta_tasks:
            for m in repo_meta_tasks:
                self.db.upsert_repo_meta_tx(
                    cur,
                    repo_name=m.get("repo_name", ""),
                    tags=m.get("tags", ""),
                    domain=m.get("domain", ""),
                    description=m.get("description", ""),
                    priority=int(m.get("priority", 0) or 0),
                )
        if snippet_rows:
            self.db.upsert_snippet_tx(cur, snippet_rows)
        if context_rows:
            self.db.upsert_context_tx(cur, context_rows)
        if failed_rows:
            self.db.upsert_failed_tasks_tx(cur, failed_rows)
        if failed_clear_paths:
            self.db.clear_failed_tasks_tx(cur, failed_clear_paths)

        if delete_paths:
            engine_deletes.extend(list(delete_paths))
        if engine_docs or engine_deletes:
            engine = getattr(self.db, "engine", None)
            try:
                if engine_docs and hasattr(engine, "upsert_documents"):
                    engine.upsert_documents(engine_docs)
                if engine_deletes and hasattr(engine, "delete_documents"):
                    engine.delete_documents(engine_deletes)
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"engine update failed: {e}")

        if self.latency_cb and latency_samples:
            for s in latency_samples:
                self.latency_cb(s)


class Indexer:
    def __init__(self, cfg: Config, db: LocalSearchDB, logger=None, indexer_mode: str = "auto", indexing_enabled: bool = True, startup_index_enabled: bool = True, lock_handle: Any = None):
        self.cfg, self.db, self.logger = cfg, db, logger
        self.status = IndexStatus()
        self.indexer_mode = indexer_mode
        self.indexing_enabled = indexing_enabled
        self.startup_index_enabled = startup_index_enabled
        self._lock_handle = lock_handle
        self._stop, self._rescan = threading.Event(), threading.Event()
        self._pipeline_started = False
        self._drain_timeout = 2.0
        self._coalesce_max_keys = 100000
        try:
            # CHECK SARI_
            raw = _get_env_any("COALESCE_SHARDS", "16")
            shard_count = int(raw or 16)
        except Exception:
            shard_count = 16
        if shard_count <= 0:
            shard_count = 1
        self._coalesce_shards = shard_count
        self._coalesce_lock = ShardedLock(self._coalesce_shards)
        self._coalesce_size_lock = threading.Lock()
        self._coalesce_size = 0
        self._coalesce_map: Dict[str, CoalesceTask] = {}
        self._legacy_purge_done = False
        self._event_queue = DedupQueue() if DedupQueue else None
        self._worker_thread = None
        batch_size = int(getattr(cfg, "commit_batch_size", 50) or 50)
        if batch_size <= 0:
            batch_size = 50
        self._db_writer = DBWriter(self.db, logger=self.logger, max_batch=batch_size, latency_cb=self._record_latency)
        self._metrics_thread = None
        self._latencies = deque(maxlen=2000)
        self._enqueue_count = 0
        self._enqueue_count_ts = time.time()
        self._retry_count = 0
        self._drop_count_degraded = 0
        self._drop_count_shutdown = 0
        self._drop_count_telemetry = 0
        self._dlq_thread = None
        max_workers = getattr(cfg, "max_workers", 4) or 4
        try:
            max_workers = int(max_workers)
        except Exception:
            max_workers = 4
        if max_workers <= 0:
            max_workers = 4
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._parse_timeout_seconds = 0.0
        self._parse_executor = None
        try:
            self._parse_timeout_seconds = float(os.environ.get("SARI_PARSE_TIMEOUT_SECONDS", "0") or 0)
        except Exception:
            self._parse_timeout_seconds = 0.0
        if self._parse_timeout_seconds > 0:
            try:
                parse_workers = int(os.environ.get("SARI_PARSE_TIMEOUT_WORKERS", "2") or 2)
            except Exception:
                parse_workers = 2
            if parse_workers <= 0:
                parse_workers = 1
            self._parse_executor = concurrent.futures.ThreadPoolExecutor(max_workers=parse_workers)
        self.watcher = None

    def stop(self):
        self._stop.set(); self._rescan.set()
        if self.watcher:
            try: self.watcher.stop()
            except: pass
        self._drain_queues()
        try: self._executor.shutdown(wait=False)
        except: pass
        if self._parse_executor:
            try:
                self._parse_executor.shutdown(wait=False)
            except Exception:
                pass
        if self._db_writer:
            self._db_writer.stop(timeout=self._drain_timeout)
        if self._dlq_thread and self._dlq_thread.is_alive():
            try:
                self._dlq_thread.join(timeout=self._drain_timeout)
            except Exception:
                pass
        if self.logger and hasattr(self.logger, "stop"):
            try:
                self.logger.stop(timeout=self._drain_timeout)
            except Exception:
                pass
        if self._lock_handle:
            try:
                self._lock_handle.release()
            except Exception:
                pass

    def request_rescan(self): self._rescan.set()

    def scan_once(self) -> None:
        """Force a synchronous scan of the workspace (used by MCP tools/tests)."""
        self._start_pipeline()
        self._scan_once()

    def run_forever(self):
        if not self.indexing_enabled:
            self.status.index_ready = True
            return
        self._start_pipeline()
        # Start watcher if available and not already running
        if FileWatcher and not self.watcher:
            try:
                # Watch all roots
                roots = [str(Path(os.path.expanduser(r)).absolute()) for r in self.cfg.workspace_roots if Path(r).exists()]
                if roots:
                    self.watcher = FileWatcher(roots, self._process_watcher_event, on_git_checkout=lambda _p: self.request_rescan())
                    self.watcher.start()
                    if self.logger: self.logger.log_info(f"FileWatcher started for {roots}")
            except Exception as e:
                if self.logger: self.logger.log_error(f"Failed to start FileWatcher: {e}")

        if self.startup_index_enabled:
            self._scan_once()
        self.status.index_ready = True
        while not self._stop.is_set():
            timeout = max(1, int(getattr(self.cfg, "scan_interval_seconds", 30)))
            self._rescan.wait(timeout=timeout)
            self._rescan.clear()
            if self._stop.is_set(): break
            self._scan_once()

    def _start_pipeline(self) -> None:
        if self._pipeline_started:
            return
        self._pipeline_started = True
        if self._db_writer:
            self._db_writer.start()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        self._metrics_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        self._metrics_thread.start()
        if not self._dlq_thread or not self._dlq_thread.is_alive():
            self._dlq_thread = threading.Thread(target=self._dlq_loop, daemon=True)
            self._dlq_thread.start()

    def _record_latency(self, value: float) -> None:
        self._latencies.append(value)

    def get_queue_depths(self) -> dict:
        watcher_q = self._event_queue.qsize() if self._event_queue else 0
        db_q = self._db_writer.qsize() if self._db_writer else 0
        telemetry_q = self.logger.get_queue_depth() if self.logger and hasattr(self.logger, "get_queue_depth") else 0
        return {"watcher": watcher_q, "db_writer": db_q, "telemetry": telemetry_q}

    def get_last_commit_ts(self) -> int:
        if self._db_writer and hasattr(self._db_writer, "last_commit_ts"):
            return int(self._db_writer.last_commit_ts or 0)
        return 0

    def _metrics_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(5.0)
            try:
                now = time.time()
                elapsed = max(1.0, now - self._enqueue_count_ts)
                enqueue_per_sec = self._enqueue_count / elapsed
                self._enqueue_count = 0
                self._enqueue_count_ts = now

                latencies = list(self._latencies)
                if latencies:
                    latencies.sort()
                    p50 = latencies[int(0.5 * (len(latencies) - 1))]
                    p95 = latencies[int(0.95 * (len(latencies) - 1))]
                else:
                    p50 = 0.0
                    p95 = 0.0

                watcher_q = self._event_queue.qsize() if self._event_queue else 0
                db_q = self._db_writer.qsize() if self._db_writer else 0
                telemetry_q = self.logger.get_queue_depth() if self.logger and hasattr(self.logger, "get_queue_depth") else 0
                telemetry_drop = self.logger.get_drop_count() if self.logger and hasattr(self.logger, "get_drop_count") else 0

                if self.logger:
                    self.logger.log_telemetry(
                        f"queue_depth watcher={watcher_q} db={db_q} telemetry={telemetry_q} "
                        f"enqueue_per_sec={enqueue_per_sec:.2f} latency_p50={p50:.3f}s latency_p95={p95:.3f}s "
                        f"retry_count={self._retry_count} drop_degraded={self._drop_count_degraded} "
                        f"drop_shutdown={self._drop_count_shutdown} telemetry_drop={telemetry_drop}"
                    )
            except Exception:
                pass

    def _drain_queues(self) -> None:
        deadline = time.time() + self._drain_timeout
        while time.time() < deadline:
            pending = 0
            if self._event_queue:
                pending += self._event_queue.qsize()
            if self._db_writer:
                pending += self._db_writer.qsize()
            if pending == 0:
                return
            time.sleep(0.05)
        remaining = 0
        if self._event_queue:
            remaining += self._event_queue.qsize()
        if self._db_writer:
            remaining += self._db_writer.qsize()
        self._drop_count_shutdown += remaining
        if self.logger:
            self.logger.log_info(f"dropped_on_shutdown={remaining}")

    def _enqueue_db_tasks(self, files_rows: List[tuple], symbols_rows: List[tuple], relations_rows: List[tuple], engine_docs: Optional[List[dict]] = None, enqueue_ts: Optional[float] = None) -> None:
        if files_rows:
            self._db_writer.enqueue(DbTask(kind="upsert_files", rows=list(files_rows), ts=enqueue_ts or time.time(), engine_docs=list(engine_docs or [])))
        if symbols_rows:
            self._db_writer.enqueue(DbTask(kind="upsert_symbols", rows=list(symbols_rows)))
        if relations_rows:
            self._db_writer.enqueue(DbTask(kind="upsert_relations", rows=list(relations_rows)))

    def _enqueue_update_last_seen(self, paths: List[str]) -> None:
        if not paths:
            return
        self._db_writer.enqueue(DbTask(kind="update_last_seen", paths=list(paths)))

    def _enqueue_delete_path(self, path: str, enqueue_ts: Optional[float] = None) -> None:
        self._db_writer.enqueue(DbTask(kind="delete_path", path=path, ts=enqueue_ts or time.time()))
        self._enqueue_dlq_clear([path])

    def _enqueue_repo_meta(self, repo_name: str, tags: str, description: str) -> None:
        self._db_writer.enqueue(
            DbTask(kind="upsert_repo_meta", repo_meta={"repo_name": repo_name, "tags": tags, "description": description})
        )

    def _enqueue_dlq_upsert(self, rows: List[tuple]) -> None:
        if not rows:
            return
        self._db_writer.enqueue(DbTask(kind="dlq_upsert", failed_rows=list(rows)))

    def _enqueue_dlq_clear(self, paths: List[str]) -> None:
        if not paths:
            return
        self._db_writer.enqueue(DbTask(kind="dlq_clear", failed_paths=list(paths)))

    def _dlq_backoff_seconds(self, attempts: int) -> int:
        if attempts <= 1:
            return 60
        if attempts == 2:
            return 300
        return 3600

    def _record_failed_task(self, path: str, err: Any, attempts: int) -> None:
        if not path:
            return
        now = int(time.time())
        safe_attempts = max(1, int(attempts))
        next_retry = now + self._dlq_backoff_seconds(safe_attempts)
        msg = str(err)[:500]
        self._enqueue_dlq_upsert([(path, safe_attempts, msg, now, next_retry)])

    def _extract_symbols_with_timeout(self, path: str, content: str) -> Tuple[List[Tuple], List[Tuple]]:
        if not self._parse_executor or self._parse_timeout_seconds <= 0:
            return _extract_symbols_with_relations(path, content)
        future = self._parse_executor.submit(_extract_symbols_with_relations, path, content)
        try:
            return future.result(timeout=self._parse_timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("parse timeout") from exc

    def _coalesce_lock_for(self, key: str) -> threading.Lock:
        return self._coalesce_lock.get_lock(key)

    def _normalize_path(self, path: str) -> Optional[str]:
        try:
            p = Path(path).absolute()
            # Multi-root support: Check if path is within any workspace root
            for root_str in self.cfg.workspace_roots:
                root = Path(os.path.expanduser(root_str)).absolute()
                try:
                    p.relative_to(root)
                    return self._encode_db_path(root, p)
                except ValueError:
                    continue
            return None
        except Exception:
            return None

    def _get_root_map(self) -> dict[str, Path]:
        roots = {}
        for r in self.cfg.workspace_roots:
            root_path = Path(os.path.expanduser(r)).absolute()
            root_id = self._root_id(str(root_path))
            roots[root_id] = root_path
        return roots

    def _encode_db_path(self, root: Path, file_path: Path) -> str:
        root_id = self._root_id(str(root))
        rel = file_path.relative_to(root).as_posix()
        return f"{root_id}/{rel}"

    def _decode_db_path(self, db_path: str) -> Optional[tuple[Path, Path]]:
        if "/" not in db_path:
            return None
        root_id, rel = db_path.split("/", 1)
        roots = self._get_root_map()
        root = roots.get(root_id)
        if not root:
            return None
        rel_path = Path(*rel.split("/"))
        return root, (root / rel_path)

    def _root_id(self, path: str) -> str:
        if WorkspaceManager is None:
            import hashlib
            digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
            return f"root-{digest}"
        return WorkspaceManager.root_id(path)

    def _enqueue_action(self, action: TaskAction, path: str, ts: float, attempts: int = 0) -> None:
        if not self._event_queue:
            return
        norm = self._normalize_path(path)
        if not norm:
            return
        # Key must be unique per file. Use db path as key.
        key = norm
        lock = self._coalesce_lock_for(key)
        with lock:
            exists = key in self._coalesce_map
            if not exists:
                with self._coalesce_size_lock:
                    if self._coalesce_size >= self._coalesce_max_keys:
                        self._drop_count_degraded += 1
                        if self.logger:
                            self.logger.log_error(f"coalesce_map degraded: drop key={key}")
                        return
                    self._coalesce_size += 1
            if exists:
                task = self._coalesce_map[key]
                task.action = coalesce_action(task.action, action)
                task.last_seen = ts
                task.enqueue_ts = ts
                task.attempts = max(task.attempts, attempts)
            else:
                self._coalesce_map[key] = CoalesceTask(action=action, path=norm, attempts=attempts, enqueue_ts=ts, last_seen=ts)
            self._event_queue.put(key)
            self._enqueue_count += 1

    def _enqueue_fsevent(self, evt: FsEvent) -> None:
        if evt.kind == FsEventKind.MOVED:
            for action, p in split_moved_event(evt):
                self._enqueue_action(action, p, evt.ts)
            return
        if evt.kind == FsEventKind.DELETED:
            self._enqueue_action(TaskAction.DELETE, evt.path, evt.ts)
            return
        self._enqueue_action(TaskAction.INDEX, evt.path, evt.ts)

    def _worker_loop(self) -> None:
        if not self._event_queue:
            return
        while not self._stop.is_set() or self._event_queue.qsize() > 0:
            keys = self._event_queue.get_batch(max_size=50, timeout=0.2)
            if not keys:
                continue
            for key in keys:
                lock = self._coalesce_lock_for(key)
                with lock:
                    task = self._coalesce_map.pop(key, None)
                if task:
                    with self._coalesce_size_lock:
                        self._coalesce_size = max(0, self._coalesce_size - 1)
                if not task:
                    continue
                if task.action == TaskAction.DELETE:
                    self._enqueue_delete_path(task.path, enqueue_ts=task.enqueue_ts)
                    continue
                self._handle_index_task(task)

    def _dlq_loop(self) -> None:
        try:
            interval = float(os.environ.get("SARI_DLQ_POLL_SECONDS", "60") or 60)
        except Exception:
            interval = 60.0
        while not self._stop.is_set():
            time.sleep(max(5.0, interval))
            if self._stop.is_set():
                break
            try:
                now = int(time.time())
                rows = self.db.list_failed_tasks_ready(now_ts=now, limit=50)
            except Exception:
                rows = []
            if not rows:
                continue
            for r in rows:
                path = str(r.get("path") or "")
                if not path:
                    continue
                attempts = int(r.get("attempts") or 0) + 1
                next_retry = int(time.time()) + self._dlq_backoff_seconds(attempts)
                last_error = str(r.get("last_error") or "")
                # bump retry window to avoid repeated enqueue in the same cycle
                self._enqueue_dlq_upsert([(path, attempts, last_error, int(time.time()), next_retry)])
                self._enqueue_action(TaskAction.INDEX, path, time.time(), attempts=attempts)

    def _handle_index_task(self, task: CoalesceTask) -> None:
        resolved = self._decode_db_path(task.path)
        if not resolved:
            return
        matched_root, file_path = resolved

        try:
            st = file_path.stat()
        except FileNotFoundError:
            self._enqueue_delete_path(task.path, enqueue_ts=task.enqueue_ts)
            return
        except (IOError, PermissionError, OSError) as e:
            self._retry_task(task, e)
            return

        try:
            res = self._process_file_task(matched_root, file_path, st, int(time.time()), time.time(), False, raise_on_error=True)
        except (IOError, PermissionError, OSError) as e:
            self._retry_task(task, e)
            return
        except Exception as e:
            self.status.errors += 1
            self._record_failed_task(task.path, e, max(1, task.attempts))
            return

        if not res or res.get("type") == "unchanged":
            self._enqueue_dlq_clear([task.path])
            return

        self._enqueue_db_tasks(
            [(
                res["rel"],
                res["repo"],
                res["mtime"],
                res["size"],
                res["content"],
                res["parse_status"],
                res["parse_reason"],
                res["ast_status"],
                res["ast_reason"],
                int(res["is_binary"]),
                int(res["is_minified"]),
                int(res["sampled"]),
                int(res["content_bytes"]),
            )],
            list(res.get("symbols") or []),
            list(res.get("relations") or []),
            engine_docs=[res.get("engine_doc")] if res.get("engine_doc") else [],
            enqueue_ts=task.enqueue_ts,
        )
        self._enqueue_dlq_clear([task.path])

    def _retry_task(self, task: CoalesceTask, err: Exception) -> None:
        if task.attempts >= 2:
            self._drop_count_degraded += 1
            if self.logger:
                self.logger.log_error(f"Task dropped after retries: {task.path} err={err}")
            self._record_failed_task(task.path, err, task.attempts + 1)
            return
        self._retry_count += 1
        task.attempts += 1
        base = 0.5 if task.attempts == 1 else 2.0
        sleep = base * random.uniform(0.8, 1.2)
        t = threading.Timer(sleep, lambda: self._enqueue_action(task.action, task.path, time.time(), attempts=task.attempts))
        t.daemon = True
        t.start()

    def _build_engine_doc(self, doc_id: str, repo: str, rel_to_root: str, content: str, parse_status: str, mtime: int, size: int) -> dict:
        rel_path = Path(rel_to_root).as_posix()
        root_id = doc_id.split("/", 1)[0] if "/" in doc_id else ""
        path_text = f"{doc_id} {rel_path}"
        max_doc_bytes = int(os.environ.get("SARI_ENGINE_MAX_DOC_BYTES", "4194304") or 4194304)
        preview_bytes = int(os.environ.get("SARI_ENGINE_PREVIEW_BYTES", "8192") or 8192)
        body_text = ""
        preview = ""
        if parse_status == "ok":
            norm = _normalize_engine_text(content or "")
            if _has_cjk(norm):
                norm = _cjk_space(norm)
            if len(norm) > max_doc_bytes:
                head = max_doc_bytes // 2
                tail = max_doc_bytes - head
                norm = norm[:head] + norm[-tail:]
            body_text = norm
            if preview_bytes > 0:
                if content and len(content) > preview_bytes:
                    half = preview_bytes // 2
                    preview = content[:half] + "\n...\n" + content[-half:]
                else:
                    preview = content or ""
        return {
            "doc_id": doc_id,
            "path": doc_id,
            "repo": repo,
            "root_id": root_id,
            "rel_path": rel_path,
            "path_text": path_text,
            "body_text": body_text,
            "preview": preview,
            "mtime": int(mtime),
            "size": int(size),
        }

    def _process_file_task(self, root: Path, file_path: Path, st: os.stat_result, scan_ts: int, now: float, excluded: bool, raise_on_error: bool = False) -> Optional[dict]:
        try:
            rel_to_root = str(file_path.relative_to(root))
            repo = rel_to_root.split(os.sep, 1)[0] if os.sep in rel_to_root else "__root__"
            db_path = self._encode_db_path(root, file_path)

            prev = self.db.get_file_meta(db_path)
            if prev and int(st.st_mtime) == int(prev[0]) and int(st.st_size) == int(prev[1]):
                if now - st.st_mtime > AI_SAFETY_NET_SECONDS:
                    return {"type": "unchanged", "rel": db_path}

            parse_limit, ast_limit = _resolve_size_limits()
            exclude_parse = _env_flag("SARI_EXCLUDE_APPLIES_TO_PARSE", True)
            exclude_ast = _env_flag("SARI_EXCLUDE_APPLIES_TO_AST", True)
            sample_large = _env_flag("SARI_SAMPLE_LARGE_FILES", False)
            decode_policy = (os.environ.get("SARI_UTF8_DECODE_POLICY") or "strong").strip().lower()

            include_ext = {e.lower() for e in getattr(self.cfg, "include_ext", [])}
            include_files = set(getattr(self.cfg, "include_files", []))
            include_files_abs = {str(Path(p).expanduser().absolute()) for p in include_files if os.path.isabs(p)}
            include_files_rel = {p for p in include_files if not os.path.isabs(p)}
            include_all_ext = not include_ext and not include_files

            parse_status = "none"
            parse_reason = "none"
            ast_status = "none"
            ast_reason = "none"
            is_binary = 0
            is_minified = 0
            sampled = 0
            content = ""
            content_bytes = 0
            symbols: List[Tuple] = []
            relations: List[Tuple] = []

            size = int(getattr(st, "st_size", 0) or 0)
            max_file_bytes = int(getattr(self.cfg, "max_file_bytes", 0) or 0)
            too_large_meta = max_file_bytes > 0 and size > max_file_bytes
            # Determine include eligibility for parse/ast
            is_included = include_all_ext
            if not is_included:
                rel = str(file_path.absolute().relative_to(root))
                is_included = (rel in include_files_rel) or (str(file_path.absolute()) in include_files_abs)
                if not is_included and include_ext:
                    is_included = file_path.suffix.lower() in include_ext
            if (include_files or include_ext) and not is_included:
                return None

            # Exclude rules for parse/ast
            if excluded and exclude_parse:
                parse_status, parse_reason = "skipped", "excluded"
                ast_status, ast_reason = "skipped", "excluded"
            elif too_large_meta:
                parse_status, parse_reason = "skipped", "too_large"
                ast_status, ast_reason = "skipped", "too_large"
            else:
                sample = _sample_file(file_path, size)
                printable_ratio = _printable_ratio(sample, policy=decode_policy)
                if printable_ratio < 0.80 or b"\x00" in sample:
                    is_binary = 1
                    parse_status, parse_reason = "skipped", "binary"
                    ast_status, ast_reason = "skipped", "binary"
                else:
                    try:
                        text_sample = sample.decode("utf-8") if decode_policy == "strong" else sample.decode("utf-8", errors="ignore")
                    except UnicodeDecodeError:
                        is_binary = 1
                        parse_status, parse_reason = "skipped", "binary"
                        ast_status, ast_reason = "skipped", "binary"
                        text_sample = ""
                    if not is_binary:
                        if _is_minified(file_path, text_sample):
                            is_minified = 1
                            parse_status, parse_reason = "skipped", "minified"
                            ast_status, ast_reason = "skipped", "minified"
                        elif size > parse_limit:
                            if sample_large:
                                sampled = 1
                                parse_status, parse_reason = "skipped", "sampled"
                                ast_status, ast_reason = "skipped", "no_parse"
                                try:
                                    if decode_policy == "strong":
                                        content = sample.decode("utf-8")
                                    else:
                                        content = sample.decode("utf-8", errors="ignore")
                                except Exception:
                                    content = ""
                                content_bytes = len(content.encode("utf-8")) if content else 0
                            else:
                                parse_status, parse_reason = "skipped", "too_large"
                                ast_status, ast_reason = "skipped", "no_parse"
                        else:
                            raw = file_path.read_bytes()
                            try:
                                text = raw.decode("utf-8") if decode_policy == "strong" else raw.decode("utf-8", errors="ignore")
                            except UnicodeDecodeError:
                                is_binary = 1
                                parse_status, parse_reason = "skipped", "binary"
                                ast_status, ast_reason = "skipped", "binary"
                                text = ""
                            if not is_binary:
                                # SSOT: empty content (non-binary) => skipped/no_parse
                                if not text:
                                    parse_status, parse_reason = "skipped", "no_parse"
                                    ast_status, ast_reason = "skipped", "no_parse"
                                    content = ""
                                    content_bytes = 0
                                else:
                                    parse_status, parse_reason = "ok", "none"
                                # Storage cap
                                exclude_bytes = getattr(self.cfg, "exclude_content_bytes", 104857600)
                                if parse_status == "ok":
                                    if len(text) > exclude_bytes:
                                        text = text[:exclude_bytes] + f"\n\n... [CONTENT TRUNCATED (File size: {len(text)} bytes, limit: {exclude_bytes})] ..."
                                    if getattr(self.cfg, "redact_enabled", True):
                                        text = _redact(text)
                                    content = text
                                    content_bytes = len(content.encode("utf-8")) if content else 0
                                    if excluded and exclude_ast:
                                        ast_status, ast_reason = "skipped", "excluded"
                                    elif size > ast_limit:
                                        ast_status, ast_reason = "skipped", "too_large"
                                    else:
                                        try:
                                            symbols, relations = self._extract_symbols_with_timeout(db_path, content)
                                            ast_status, ast_reason = "ok", "none"
                                        except TimeoutError:
                                            ast_status, ast_reason = "timeout", "timeout"
                                        except Exception:
                                            ast_status, ast_reason = "error", "error"

            return {
                "type": "changed",
                "rel": db_path,
                "repo": repo,
                "mtime": int(st.st_mtime),
                "size": size,
                "content": content,
                "scan_ts": scan_ts,
                "symbols": symbols,
                "relations": relations,
                "parse_status": parse_status,
                "parse_reason": parse_reason,
                "ast_status": ast_status,
                "ast_reason": ast_reason,
                "is_binary": is_binary,
                "is_minified": is_minified,
                "sampled": sampled,
                "content_bytes": content_bytes,
                "engine_doc": self._build_engine_doc(db_path, repo, rel_to_root, content, parse_status, int(st.st_mtime), size),
            }
        except Exception:
            self.status.errors += 1
            if raise_on_error:
                raise
            try:
                return {"type": "unchanged", "rel": self._encode_db_path(root, file_path)}
            except Exception:
                return None

    def _process_meta_file(self, path: Path, repo: str) -> None:
        if path.name != "package.json":
            return
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(raw)
        except Exception:
            return

        description = ""
        tags: list[str] = []
        if isinstance(data, dict):
            description = str(data.get("description", "") or "")
            keywords = data.get("keywords", [])
            if isinstance(keywords, list):
                tags = [str(t) for t in keywords if t]
            elif isinstance(keywords, str):
                tags = [k.strip() for k in keywords.split(",") if k.strip()]

        if not description and not tags:
            return

        tags_str = ",".join(tags)
        self._enqueue_repo_meta(repo, tags_str, description)

    def _iter_file_entries_stream(self, root: Path, apply_exclude: bool = True):
        exclude_dirs = set(getattr(self.cfg, "exclude_dirs", []))
        exclude_globs = list(getattr(self.cfg, "exclude_globs", []))

        for dirpath, dirnames, filenames in os.walk(root):
            if dirnames and apply_exclude:
                kept = []
                for d in dirnames:
                    if d in exclude_dirs:
                        continue
                    rel_dir = str((Path(dirpath) / d).absolute().relative_to(root))
                    if any(fnmatch.fnmatch(rel_dir, pat) or fnmatch.fnmatch(d, pat) for pat in exclude_dirs):
                        continue
                    kept.append(d)
                dirnames[:] = kept
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    rel = str(p.absolute().relative_to(root))
                except Exception:
                    continue
                excluded = any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(fn, pat) for pat in exclude_globs)
                if not excluded and exclude_dirs:
                    rel_parts = rel.split(os.sep)
                    for part in rel_parts:
                        if part in exclude_dirs:
                            excluded = True
                            break
                        if any(fnmatch.fnmatch(part, pat) for pat in exclude_dirs):
                            excluded = True
                            break
                try:
                    st = p.stat()
                except Exception:
                    self.status.errors += 1
                    continue
                if apply_exclude and excluded:
                    continue
                yield p, st, excluded

    def _iter_file_entries(self, root: Path) -> List[Tuple[Path, os.stat_result]]:
        return [(p, st) for p, st, _ in self._iter_file_entries_stream(root)]

    def _iter_files(self, root: Path) -> List[Path]:
        """Return candidate file paths (legacy tests expect Path objects)."""
        return [p for p, _ in self._iter_file_entries(root)]

    def _scan_once(self):
        # Optional: purge legacy db paths (one-time)
        if not self._legacy_purge_done:
            flag = os.environ.get("SARI_PURGE_LEGACY_PATHS", "0").strip().lower()
            if flag in ("1", "true", "yes", "on"):
                try:
                    purged = self.db.purge_legacy_paths()
                    if self.logger:
                        self.logger.log_info(f"purged_legacy_paths={purged}")
                except Exception:
                    if self.logger:
                        self.logger.log_error("failed to purge legacy paths")
            self._legacy_purge_done = True

        # Iterate over all workspace roots
        all_roots = [Path(os.path.expanduser(r)).absolute() for r in self.cfg.workspace_roots]
        valid_roots = [r for r in all_roots if r.exists()]

        now, scan_ts = time.time(), int(time.time())
        self.status.last_scan_ts, self.status.scanned_files = now, 0

        batch_files, batch_syms, batch_rels, unchanged = [], [], [], []

        chunk_size = 100
        chunk = []

        exclude_meta = _env_flag("SARI_EXCLUDE_APPLIES_TO_META", True)
        for root in valid_roots:
            for entry in self._iter_file_entries_stream(root, apply_exclude=exclude_meta):
                chunk.append(entry)
                self.status.scanned_files += 1
                if len(chunk) < chunk_size:
                    continue
                self._process_chunk(root, chunk, scan_ts, now, batch_files, batch_syms, batch_rels, unchanged)
                chunk = []
            if chunk:
                self._process_chunk(root, chunk, scan_ts, now, batch_files, batch_syms, batch_rels, unchanged)
                chunk = []

        if batch_files or batch_syms or batch_rels:
            self._enqueue_db_tasks(batch_files, batch_syms, batch_rels)
            self.status.indexed_files += len(batch_files)
        if unchanged:
            self._enqueue_update_last_seen(unchanged)
        try:
            unseen_paths = self.db.get_unseen_paths(scan_ts)
            for p in unseen_paths:
                self._enqueue_delete_path(p)
        except Exception as e:
            self.status.errors += 1

    def _process_chunk(self, root, chunk, scan_ts, now, batch_files, batch_syms, batch_rels, unchanged):
        futures = [self._executor.submit(self._process_file_task, root, f, s, scan_ts, now, excluded) for f, s, excluded in chunk]

        for f, s, _ in chunk:
            if f.name == "package.json":
                rel = str(f.relative_to(root))
                repo = rel.split(os.sep, 1)[0] if os.sep in rel else "__root__"
                self._process_meta_file(f, repo)

        for future in concurrent.futures.as_completed(futures):
            try: res = future.result()
            except: self.status.errors += 1; continue
            if not res: continue
            if res["type"] == "unchanged":
                unchanged.append(res["rel"])
                if len(unchanged) >= 100:
                    self._enqueue_update_last_seen(unchanged)
                    unchanged.clear()
                continue

            batch_files.append(
                (
                    res["rel"],
                    res["repo"],
                    res["mtime"],
                    res["size"],
                    res["content"],
                    res["parse_status"],
                    res["parse_reason"],
                    res["ast_status"],
                    res["ast_reason"],
                    int(res["is_binary"]),
                    int(res["is_minified"]),
                    int(res["sampled"]),
                    int(res["content_bytes"]),
                )
            )
            if res.get("symbols"):
                batch_syms.extend(res["symbols"])
            if res.get("relations"):
                batch_rels.extend(res["relations"])

            if len(batch_files) >= 50:
                self._enqueue_db_tasks(batch_files, batch_syms, batch_rels)
                self.status.indexed_files += len(batch_files)
                batch_files.clear()
                batch_syms.clear()
                batch_rels.clear()

    def _process_watcher_event(self, evt: FsEvent):
        try:
            self._enqueue_fsevent(evt)
        except Exception:
            self.status.errors += 1
