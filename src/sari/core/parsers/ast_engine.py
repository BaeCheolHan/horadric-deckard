from typing import Any, Optional, List, Tuple, Dict
import json
import logging
import re
from .common import _qualname, _symbol_id
from .handlers import HandlerRegistry

try:
    import tree_sitter
    from tree_sitter import Parser
    from tree_sitter_languages import get_language
    HAS_LIBS = True
except ImportError:
    HAS_LIBS = False

class ASTEngine:
    """
    ASTEngine V28 - Ultra-Resilient Engine.
    Forces language setting on parser and features deep-crawl name extraction.
    """
    def __init__(self):
        self.logger = logging.getLogger("sari.ast")
        self.registry = HandlerRegistry()
    
    @property
    def enabled(self) -> bool: return HAS_LIBS
    
    def _get_language(self, name: str) -> Any:
        if not HAS_LIBS: return None
        m = {"hcl": "hcl", "tf": "hcl", "py": "python", "js": "javascript", "ts": "typescript", "java": "java", "kt": "kotlin", "rs": "rust", "go": "go", "sh": "bash", "sql": "sql", "swift": "swift"}
        target = m.get(name.lower(), name.lower())
        try: return get_language(target)
        except: return None

    def parse(self, language: str, content: str) -> Optional[Any]:
        """Safely parse content with explicit language setting."""
        if not HAS_LIBS: return None
        lang_obj = self._get_language(language)
        if not lang_obj: return None
        parser = Parser(); parser.set_language(lang_obj)
        return parser.parse(content.encode("utf-8", errors="ignore"))

    def extract_symbols(self, path: str, language: str, content: str, tree: Any = None) -> Tuple[List[Tuple], List[Any]]:
        if not content: return [], []
        ext = path.split(".")[-1].lower() if "." in path else language.lower()
        
        # Specialized Fallbacks (MyBatis, JSP etc)
        if ext == "xml": return self._mybatis(path, content), []
        if ext == "jsp": return self._jsp(path, content), []
        if ext in ("md", "markdown"): return self._markdown(path, content), []

        lang_obj = self._get_language(ext)
        if not lang_obj: 
            self.logger.warning(f"No TS language found for: {ext}. Skipping AST.")
            return [], []
        
        if tree is None:
            tree = self.parse(ext, content)
        if not tree: return [], []

        data = content.encode("utf-8", errors="ignore"); lines = content.splitlines(); symbols = []

        def get_t(n): return data[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")
        def get_child(n, *types):
            for c in n.children:
                if c.type in types: return c
            return None

        def find_id_aggressive(node):
            """Deep crawl to find any identifier-like node."""
            if node.type in ("identifier", "name", "type_identifier", "constant"): return get_t(node)
            for c in node.children:
                res = find_id_aggressive(c)
                if res: return res
            return None

        handler = self.registry.get_handler(ext)

        def walk(node, p_name="", p_meta=None):
            kind, name, meta, is_valid = None, None, {"annotations": []}, False
            n_type = node.type
            
            if handler:
                kind, name, meta, is_valid = handler.handle_node(node, get_t, find_id_aggressive, ext, p_meta or {})
                if is_valid and not name: name = find_id_aggressive(node)
                
                if is_valid and hasattr(handler, "extract_api_info"):
                    api_info = handler.extract_api_info(node, get_t, get_child)
                    if api_info.get("http_path"):
                        cp = p_meta.get("http_path", "") if p_meta else ""
                        meta["http_path"] = (cp + api_info["http_path"]).replace("//", "/")
                        meta["http_methods"] = api_info.get("http_methods", [])
            else:
                if n_type in ("class_declaration", "function_definition", "method_declaration", "block", "resource", "create_table_statement", "class", "method"):
                    kind = "class" if any(x in n_type for x in ("class", "struct", "enum", "block", "resource", "table")) else "function"
                    is_valid, name = True, find_id_aggressive(node)

            if is_valid and name:
                start, end = node.start_point[0] + 1, node.end_point[0] + 1
                symbols.append((path, name, kind, start, end, lines[start-1].strip() if start <= len(lines) else "", p_name, json.dumps(meta), "", name, _symbol_id(path, kind, name)))
                p_name, p_meta = name, meta
            for child in node.children: walk(child, p_name, p_meta)

        walk(tree.root_node, p_meta={}); return symbols, []

    def _mybatis(self, p, c):
        # Basic MyBatis extraction if needed
        return []
    def _markdown(self, p, c): return []
    def _jsp(self, p, c): return []