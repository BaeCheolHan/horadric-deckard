from typing import Any, Optional, List, Tuple
import json
import importlib
from .common import _qualname, _symbol_id

# 1. Try to check if core tree-sitter is installed
try:
    import tree_sitter
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

# 2. Try to get legacy get_parser if available
try:
    from tree_sitter_languages import get_parser as legacy_get_parser
except ImportError:
    legacy_get_parser = None

class ASTEngine:
    """
    Handles incremental AST parsing using Tree-sitter.
    Supports both tree-sitter-languages (monolith) and individual packages (e.g., tree-sitter-python).
    """
    def __init__(self):
        self.enabled = HAS_TREE_SITTER or (legacy_get_parser is not None)
        self._parsers = {}
        self._languages = {}

    def _get_language(self, language: str) -> Any:
        """Dynamically load language package if available."""
        if language in self._languages:
            return self._languages[language]
        
        # Try individual package (modern standard)
        # e.g., tree_sitter_python, tree_sitter_javascript
        pkg_name = f"tree_sitter_{language}"
        try:
            mod = importlib.import_module(pkg_name)
            if hasattr(mod, "language"):
                lang = mod.language()
                self._languages[language] = lang
                return lang
        except ImportError:
            pass

        return None

    def parse(self, language: str, content: str, old_tree: Any = None) -> Any:
        if not self.enabled or not language:
            return None
        
        try:
            if language not in self._parsers:
                # 1. Try legacy get_parser (bundled)
                if legacy_get_parser:
                    try:
                        parser = legacy_get_parser(language)
                        self._parsers[language] = parser
                    except Exception:
                        pass
                
                # 2. Try core tree_sitter with individual package
                if language not in self._parsers and HAS_TREE_SITTER:
                    lang_obj = self._get_language(language)
                    if lang_obj:
                        from tree_sitter import Parser
                        parser = Parser()
                        parser.set_language(lang_obj)
                        self._parsers[language] = parser
            
            parser = self._parsers.get(language)
            if not parser:
                return None

            data = content.encode("utf-8", errors="ignore")
            if old_tree is not None:
                return parser.parse(data, old_tree)
            return parser.parse(data)
        except Exception:
            return None

    def extract_symbols(self, path: str, language: str, content: str, tree: Any = None) -> List[Tuple]:
        if not self.enabled or not language:
            return []
        
        # Normalize language name for mapping
        lang_key = language.lower()
        if lang_key == "tsx": lang_key = "tsx" # handled
        elif lang_key == "typescript": lang_key = "typescript"
        
        tree = tree or self.parse(lang_key, content)
        if not tree:
            return []
        
        lines = content.splitlines()
        symbols: List[Tuple] = []

        type_map = {
            "python": {"function_definition": "function", "class_definition": "class"},
            "javascript": {"function_declaration": "function", "method_definition": "method", "class_declaration": "class", "arrow_function": "function"},
            "typescript": {"function_declaration": "function", "method_definition": "method", "class_declaration": "class", "interface_declaration": "class"},
            "tsx": {"function_declaration": "function", "method_definition": "method", "class_declaration": "class", "interface_declaration": "class"},
            "java": {"class_declaration": "class", "interface_declaration": "class", "method_declaration": "method"},
            "go": {"function_declaration": "function", "method_declaration": "method", "type_spec": "class"},
            "rust": {"function_item": "function", "struct_item": "class", "enum_item": "class", "trait_item": "class"},
            "cpp": {"function_definition": "function", "class_specifier": "class", "struct_specifier": "class"},
            "c": {"function_definition": "function", "struct_specifier": "class"},
            "kotlin": {"class_declaration": "class", "object_declaration": "class", "function_declaration": "function"},
        }
        node_kind = type_map.get(lang_key, {})

        data = content.encode("utf-8", errors="ignore")

        def get_name(n) -> Optional[str]:
            try:
                name_node = n.child_by_field_name("name")
                if name_node:
                    return data[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
            except Exception:
                pass
            return None

        def visit(node, parent_name: str, parent_qual: str):
            kind = node_kind.get(node.type)
            cur_parent_name = parent_name
            cur_parent_qual = parent_qual
            if kind:
                name = get_name(node)
                if name:
                    start_line = node.start_point[0] + 1
                    end_line = node.end_point[0] + 1
                    raw = lines[start_line - 1].strip() if 0 < start_line <= len(lines) else ""
                    qual = _qualname(parent_qual, name)
                    sid = _symbol_id(path, kind, qual)
                    symbols.append((
                        path, name, kind, start_line, end_line, raw, parent_name,
                        json.dumps({}), "", qual, sid
                    ))
                    cur_parent_name = name
                    cur_parent_qual = qual
            
            # Recursive visit
            if hasattr(node, "children"):
                for child in node.children:
                    visit(child, cur_parent_name, cur_parent_qual)

        visit(tree.root_node, "", "")
        symbols.sort(key=lambda s: (s[3], 0 if s[2] in {"class", "interface", "enum", "record"} else 1, s[1]))
        return symbols
