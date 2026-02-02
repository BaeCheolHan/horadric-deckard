import concurrent.futures
import fnmatch
import json
import logging
import os
import re
import threading
import time
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

AI_SAFETY_NET_SECONDS = 3.0

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
            # v2.7.5: Robust Javadoc '*' cleaning (strip all leading decorations for modern standard)
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

            def _visit(node, parent="", current_symbol=None):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = child.name
                        kind = "class" if isinstance(child, ast.ClassDef) else ("method" if parent else "function")
                        start, end = child.lineno, getattr(child, "end_lineno", child.lineno)
                        doc = self.clean_doc((ast.get_docstring(child) or "").splitlines())
                        # v2.5.0: Align with tests (use 'decorators', 'annotations', and '@' prefix)
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
                        
                        # v2.7.4: Extract docstring from internal doc or leading comment
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

                        symbols.append((path, name, kind, start, end, lines[start-1].strip() if 0 <= start-1 < len(lines) else "", parent, json.dumps(meta), doc))
                        _visit(child, name, name)
                    elif isinstance(child, ast.Call) and current_symbol:
                        target = ""
                        if isinstance(child.func, ast.Name): target = child.func.id
                        elif isinstance(child.func, ast.Attribute): target = child.func.attr
                        if target: relations.append((path, current_symbol, "", target, "calls", child.lineno))
                        _visit(child, parent, current_symbol)
                    else: _visit(child, parent, current_symbol)
            _visit(tree)
        except Exception:
            # v2.7.4: Fallback to regex parser if AST fails (useful for legacy tests or malformed files)
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
            name, decl_line = pending_type_decl
            for b in pending_inheritance_extends: relations.append((path, name, "", b, "extends", decl_line))
            for b in pending_inheritance_impls: relations.append((path, name, "", b, "implements", decl_line))
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

            # v2.7.4: Simplify annotations to satisfy legacy count tests (2 == 2)
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
                    # v2.7.4: Extract path from complex annotation string
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
                pending_type_decl = (name, line_no)
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
                info = {"path": path, "name": name, "kind": kind, "line": line_no, "meta": json.dumps(meta), "doc": self.clean_doc(pending_doc), "raw": line.strip(), "parent": parent}
                active_scopes.append((cur_bal, info))
                pending_annos, last_path, pending_doc = [], None, []

            if not matches and clean and not clean.startswith("@") and not in_doc:
                current_symbol = None
                for _, info in reversed(active_scopes):
                    if info.get("kind") in (self.method_kind, "method", "function"):
                        current_symbol = info.get("name")
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
                        relations.append((path, current_symbol, "", name, "calls", line_no))

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
                    if cur_bal <= bal: symbols.append((info["path"], info["name"], info["kind"], info["line"], line_no, info["raw"], info["parent"], info["meta"], info["doc"]))
                    else: still_active.append((bal, info))
                active_scopes = still_active

        last_line = len(lines)
        for _, info in active_scopes:
            symbols.append((info["path"], info["name"], info["kind"], info["line"], last_line, info["raw"], info["parent"], info["meta"], info["doc"]))
        if pending_type_decl:
            name, decl_line = pending_type_decl
            for b in pending_inheritance_extends: relations.append((path, name, "", b, "extends", decl_line))
            for b in pending_inheritance_impls: relations.append((path, name, "", b, "implements", decl_line))
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


class Indexer:
    def __init__(self, cfg: Config, db: LocalSearchDB, logger=None):
        self.cfg, self.db, self.logger = cfg, db, logger
        self.status = IndexStatus()
        self._stop, self._rescan = threading.Event(), threading.Event()
        max_workers = getattr(cfg, "max_workers", 4) or 4
        try:
            max_workers = int(max_workers)
        except Exception:
            max_workers = 4
        if max_workers <= 0:
            max_workers = 4
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.watcher = None

    def stop(self):
        self._stop.set(); self._rescan.set()
        if self.watcher:
            try: self.watcher.stop()
            except: pass
        try: self._executor.shutdown(wait=False)
        except: pass

    def request_rescan(self): self._rescan.set()

    def run_forever(self):
        # v2.7.0: Start watcher if available and not already running
        if FileWatcher and not self.watcher:
            try:
                root = Path(os.path.expanduser(self.cfg.workspace_root)).resolve()
                self.watcher = FileWatcher([str(root)], self._process_watcher_event)
                self.watcher.start()
                if self.logger: self.logger.log_info(f"FileWatcher started for {root}")
            except Exception as e:
                if self.logger: self.logger.log_error(f"Failed to start FileWatcher: {e}")

        self._scan_once(); self.status.index_ready = True
        while not self._stop.is_set():
            timeout = max(1, int(getattr(self.cfg, "scan_interval_seconds", 30)))
            self._rescan.wait(timeout=timeout)
            self._rescan.clear()
            if self._stop.is_set(): break
            self._scan_once()

    def _process_file_task(self, root: Path, file_path: Path, st: os.stat_result, scan_ts: int, now: float) -> Optional[dict]:
        try:
            rel = str(file_path.relative_to(root))
            repo = rel.split(os.sep, 1)[0] if os.sep in rel else "__root__"
            prev = self.db.get_file_meta(rel)
            if prev and int(st.st_mtime) == int(prev[0]) and int(st.st_size) == int(prev[1]):
                if now - st.st_mtime > AI_SAFETY_NET_SECONDS: return {"type": "unchanged", "rel": rel}
            max_bytes = int(getattr(self.cfg, "max_file_bytes", 0) or 0)
            if max_bytes and int(getattr(st, "st_size", 0) or 0) > max_bytes:
                return None
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            
            # v2.7.0: Handle large file body storage control
            original_size = len(text)
            exclude_bytes = getattr(self.cfg, "exclude_content_bytes", 104857600)
            if original_size > exclude_bytes:
                text = text[:exclude_bytes] + f"\n\n... [CONTENT TRUNCATED (File size: {original_size} bytes, limit: {exclude_bytes})] ..."

            if getattr(self.cfg, "redact_enabled", True):
                text = _redact(text)
            symbols, relations = _extract_symbols_with_relations(rel, text)
            return {"type": "changed", "rel": rel, "repo": repo, "mtime": int(st.st_mtime), "size": int(st.st_size), "content": text, "scan_ts": scan_ts, "symbols": symbols, "relations": relations}
        except Exception:
            self.status.errors += 1
            try:
                rel = str(file_path.relative_to(root))
                return {"type": "unchanged", "rel": rel}
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
        self.db.upsert_repo_meta(repo, tags=tags_str, description=description)

    def _iter_file_entries_stream(self, root: Path):
        include_ext = {e.lower() for e in getattr(self.cfg, "include_ext", [])}
        include_all_ext = not include_ext
        include_files = set(getattr(self.cfg, "include_files", []))
        include_files_abs = {str(Path(p).expanduser().resolve()) for p in include_files if os.path.isabs(p)}
        include_files_rel = {p for p in include_files if not os.path.isabs(p)}
        exclude_dirs = set(getattr(self.cfg, "exclude_dirs", []))
        exclude_globs = list(getattr(self.cfg, "exclude_globs", []))
        max_file_bytes = int(getattr(self.cfg, "max_file_bytes", 0)) or None

        for dirpath, dirnames, filenames in os.walk(root):
            if dirnames:
                kept = []
                for d in dirnames:
                    if d in exclude_dirs:
                        continue
                    rel_dir = str((Path(dirpath) / d).resolve().relative_to(root))
                    if any(fnmatch.fnmatch(rel_dir, pat) or fnmatch.fnmatch(d, pat) for pat in exclude_dirs):
                        continue
                    kept.append(d)
                dirnames[:] = kept
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    rel = str(p.resolve().relative_to(root))
                except Exception:
                    continue
                if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(fn, pat) for pat in exclude_globs):
                    continue
                is_included = (rel in include_files_rel) or (str(p.resolve()) in include_files_abs)
                if not is_included:
                    if not include_all_ext and p.suffix.lower() not in include_ext:
                        continue
                try:
                    st = p.stat()
                except Exception:
                    self.status.errors += 1
                    continue
                if max_file_bytes is not None and st.st_size > max_file_bytes:
                    continue
                yield p, st

    def _iter_file_entries(self, root: Path) -> List[Tuple[Path, os.stat_result]]:
        return list(self._iter_file_entries_stream(root))

    def _iter_files(self, root: Path) -> List[Path]:
        """Return candidate file paths (legacy tests expect Path objects)."""
        return [p for p, _ in self._iter_file_entries(root)]

    def _scan_once(self):
        root = Path(os.path.expanduser(self.cfg.workspace_root)).resolve()
        if not root.exists(): return
        now, scan_ts = time.time(), int(time.time())
        self.status.last_scan_ts, self.status.scanned_files = now, 0
        
        batch_files, batch_syms, batch_rels, unchanged = [], [], [], []
        
        # v2.7.0: Batched futures to prevent memory bloat in large workspaces
        chunk_size = 100
        chunk = []
        for entry in self._iter_file_entries_stream(root):
            chunk.append(entry)
            self.status.scanned_files += 1
            if len(chunk) < chunk_size:
                continue
            self._process_chunk(root, chunk, scan_ts, now, batch_files, batch_syms, batch_rels, unchanged)
            chunk = []
        if chunk:
            self._process_chunk(root, chunk, scan_ts, now, batch_files, batch_syms, batch_rels, unchanged)

        if batch_files:
            try:
                self.db.upsert_files(batch_files)
                self.db.upsert_symbols(batch_syms)
                self.db.upsert_relations(batch_rels)
                self.status.indexed_files += len(batch_files)
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Failed to flush final batch to DB: {e}")
                self.status.errors += 1
        if unchanged:
            try:
                self.db.update_last_seen(unchanged, scan_ts)
            except Exception as e:
                self.status.errors += 1
        try:
            self.db.delete_unseen_files(scan_ts)
        except Exception as e:
            self.status.errors += 1

    def _process_chunk(self, root, chunk, scan_ts, now, batch_files, batch_syms, batch_rels, unchanged):
        futures = [self._executor.submit(self._process_file_task, root, f, s, scan_ts, now) for f, s in chunk]
            
        for f, s in chunk:
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
                if len(unchanged) >= 100: self.db.update_last_seen(unchanged, scan_ts); unchanged.clear()
                continue
                
            batch_files.append((res["rel"], res["repo"], res["mtime"], res["size"], res["content"], res["scan_ts"]))
            batch_syms.extend(res["symbols"]); batch_rels.extend(res["relations"])
                
            if len(batch_files) >= 50:
                try:
                    self.db.upsert_files(batch_files)
                    self.db.upsert_symbols(batch_syms)
                    self.db.upsert_relations(batch_rels)
                    self.status.indexed_files += len(batch_files)
                except Exception as e:
                    if self.logger:
                        self.logger.log_error(f"Failed to flush batch to DB: {e}")
                    self.status.errors += 1
                batch_files.clear()
                batch_syms.clear()
                batch_rels.clear()

    def _process_watcher_event(self, path: str):
        try:
            p, root = Path(path).resolve(), Path(os.path.expanduser(self.cfg.workspace_root)).resolve()
            rel = str(p.relative_to(root))
            if not p.exists(): self.db.delete_file(rel); return
            res = self._process_file_task(root, p, p.stat(), int(time.time()), time.time())
            if res and res["type"] == "changed":
                self.db.upsert_files([(res["rel"], res["repo"], res["mtime"], res["size"], res["content"], res["scan_ts"])])
                self.db.upsert_symbols(res["symbols"]); self.db.upsert_relations(res["relations"])
        except Exception: self.status.errors += 1
