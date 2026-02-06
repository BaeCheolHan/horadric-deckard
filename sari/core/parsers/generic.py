import re
import json
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path
from .base import BaseParser
from .common import _qualname, _symbol_id, _safe_compile, NORMALIZE_KIND_BY_EXT

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
        # Support @annotations, @doc, @impl, etc.
        self.re_anno = _safe_compile(r"^\s*@([a-zA-Z0-9_]+)(?:\s*\((?:(?!@).)*?\))?|@([a-zA-Z0-9_]+)")
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

    def sanitize(self, line: str) -> str:
        """Strip single-line comments and strings to prevent false matches."""
        # Strip single line comments
        line = re.sub(r"//.*$", "", line)
        line = re.sub(r"#.*$", "", line)
        # Replace string contents but keep quotes to preserve structure
        line = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', line)
        line = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", line)
        return line

    def extract(self, path: str, content: str) -> Tuple[List[Tuple], List[Tuple]]:
        symbols, relations = [], []
        js_like_ext = {".js", ".jsx", ".ts", ".tsx", ".vue"}
        js_noise_names = {
            "if", "for", "while", "switch", "catch", "return", "new", "class", "interface",
            "enum", "case", "do", "else", "try", "throw", "throws", "super", "this",
            "function", "const", "let", "var", "default",
        }
        
        # Pre-process: Blank out block comments while preserving line count
        # This prevents matching symbols inside multi-line comments.
        processed_content = content
        for m in re.finditer(r"/\*.*?\*/", content, re.DOTALL):
            replacement = "\n" * m.group(0).count("\n")
            # We use spaces to maintain columns if needed, but \n is enough for line-based regex
            processed_content = processed_content[:m.start()] + replacement + processed_content[m.end():]
        
        lines = processed_content.splitlines()
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

            m_annos = list(self.re_anno.finditer(line))
            if m_annos:
                for m_anno in m_annos:
                    tag = m_anno.group(1) or m_anno.group(2)
                    if not tag:
                        continue
                    tag_upper = tag.upper()
                    prefixed = f"@{tag}"
                    if prefixed not in pending_annos:
                        pending_annos.append(prefixed)
                    if tag_upper not in pending_annos:
                        pending_annos.append(tag_upper)
                    # Extract path from complex annotation string
                    path_match = re.search(r'"([^"]+)"', m_anno.group(0))
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
                bool(re.search(r"\b[a-zA-Z_][a-zA-Z0-9_<>,.\[\]]+\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", method_line)) or
                # Support direct method definitions: name() { ... }
                bool(re.search(r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)\s*\{", method_line)) or
                # Support arrow functions with block or expression body.
                bool(re.search(r"=>", method_line))
            )
            if looks_like_def:
                for m in self.re_method.finditer(method_line):
                    # Get the first non-None group from the match
                    name = next((g for g in m.groups() if g), None)
                    if name and not any(name == x[0] for x in matches): 
                        matches.append((name, self.method_kind, m.start()))

            filtered_matches: List[Tuple[str, str, int]] = []
            for name, kind, pos in sorted(matches, key=lambda x: x[2]):
                if self.ext in js_like_ext:
                    if name in js_noise_names:
                        continue
                    # Regex fallback frequently captures single-letter temp variables in JS/Vue.
                    if len(name) < 2:
                        continue
                filtered_matches.append((name, kind, pos))

            for name, kind, _ in filtered_matches:
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

            if not filtered_matches and clean and not clean.startswith("@") and not in_doc:
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

            if not filtered_matches and clean and not clean.startswith("@") and not in_doc:
                if "{" not in clean and "}" not in clean: pending_doc = []

            if not filtered_matches and "(" not in clean and not clean.startswith("@"):
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

        # Vue SFC quality: expose component name as a class-like symbol by filename.
        if self.ext == ".vue":
            stem = Path(path).stem.strip()
            if stem:
                has_component = any(s[1] == stem and s[2] in {"class", "interface"} for s in symbols)
                if not has_component:
                    sid = _symbol_id(path, "class", stem)
                    symbols.append((
                        path,
                        stem,
                        "class",
                        1,
                        max(1, last_line),
                        stem,
                        "",
                        "{}",
                        "",
                        stem,
                        sid,
                    ))
        symbols.sort(key=lambda s: (s[3], 0 if s[2] in {"class", "interface", "enum", "record"} else 1, s[1]))
        return symbols, relations
