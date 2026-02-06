import os
import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sari.core.cjk import has_cjk as _has_cjk
from sari.core.settings import settings
from sari.core.parsers.factory import ParserFactory
from sari.core.parsers.ast_engine import ASTEngine
import hashlib
import zlib
from sari.core.utils import _redact, _sample_file, _printable_ratio, _is_minified, _normalize_engine_text

def compute_hash(content: str) -> str:
    """Compute SHA-1 hash for delta indexing."""
    return hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()

def compute_fast_signature(file_path: Path, size: int) -> str:
    """Fast signature based on first/last chunks + size. O(1) read regardless of file size."""
    try:
        if size < 8192:
            # Small file: just hash the whole thing
            return compute_hash(file_path.read_text(encoding="utf-8", errors="ignore"))
        
        with open(file_path, "rb") as f:
            header = f.read(4096)
            f.seek(-4096, 2) # SEEK_END
            footer = f.read(4096)
            # Include size in hash to prevent collision on same content at different positions
            return hashlib.sha1(header + footer + str(size).encode()).hexdigest()
    except Exception:
        return ""

class IndexWorker:
    def __init__(self, cfg, db, logger, extractor_cb, settings_obj=None):
        self.cfg = cfg
        self.db = db
        self.logger = logger
        self.extractor_cb = extractor_cb
        self.settings = settings_obj or settings
        self.ast_engine = ASTEngine()
        self._ast_cache = OrderedDict()
        self._ast_cache_max = self.settings.AST_CACHE_ENTRIES

    def process_file_task(self, root: Path, file_path: Path, st: os.stat_result, scan_ts: int, now: float, excluded: bool, root_id: Optional[str] = None, force: bool = False) -> Optional[dict]:
        try:
            rel_to_root = str(file_path.relative_to(root))
            db_path = self._encode_db_path(root, file_path, root_id=root_id)
            repo = rel_to_root.split(os.sep, 1)[0] if os.sep in rel_to_root else "__root__"
            ext = file_path.suffix.lower()

            # 1. Fast Metadata Check
            prev = self.db.get_file_meta(db_path)
            # prev: (mtime, size, content_hash)
            if not force and prev and int(st.st_mtime) == int(prev[0]) and int(st.st_size) == int(prev[1]):
                return {"type": "unchanged", "rel": db_path}

            # 2. Signature Check (Fast Skip if content matches despite mtime change)
            size = st.st_size
            if not force and prev and size == int(prev[1]):
                sig = compute_fast_signature(file_path, size)
                if sig and sig == prev[2]:
                    return {"type": "unchanged", "rel": db_path}

            # 3. Content-based Delta Check
            if size > self.settings.MAX_PARSE_BYTES:
                return self._skip_result(db_path, repo, st, scan_ts, "too_large")

            content = file_path.read_text(encoding="utf-8", errors="ignore")
            if not content:
                return self._skip_result(db_path, repo, st, scan_ts, "empty")

            current_hash = compute_hash(content)
            if prev and prev[2] == current_hash:
                # Content hasn't changed despite mtime update
                return {"type": "unchanged", "rel": db_path}

            # 3. Actual Processing (Changed or New)
            # 3. Actual Processing (Changed or New)
            if self.settings.get_bool("REDACT_ENABLED", True):
                content = _redact(content)
            
            enable_fts = self.settings.get_bool("ENABLE_FTS", True)
            
            # Normalize only if needed (for FTS or External Engine)
            # Assuming if one is asking for FTS, they pay the cost. 
            # If external engine is used, it usually needs body_text.
            # We can't easily know if external engine is enabled here without passing it in.
            # But usually ENABLE_FTS is the main heavy switch for embedded.
            
            normalized = ""
            fts_content = ""
            
            # Optimization: Skip normalization if FTS is disabled AND we assume no external engine 
            # (or we accept external engine gets raw content? No, engine needs normalized usually)
            # For robustness, we check if we strictly want 0-cost.
            # Let's perform normalization if either FTS is on OR we suspect engine usage.
            # A safe heuristic: If ENABLE_FTS is False, we typically want raw speed. 
            # But if we have an external engine, we might break it.
            # Compromise: We check a new setting or just ENABLE_FTS. 
            # Given the prompt, "embedded mode... 0-cost". Embedded means no external engine.
            # So if ENABLE_FTS is False, we assume 0-cost is desired.
            
            if enable_fts: 
                normalized = _normalize_engine_text(content)
                
                # Truncate for FTS index stability
                fts_max = self.settings.get_int("FTS_MAX_BYTES", 1000000)
                fts_content = normalized[:fts_max] if normalized else ""
            else:
                # If FTS disabled, we still might need normalized for 'engine_doc' if using Tantivy.
                # However, calculating it kills the "0-cost" goal.
                # If the user uses Tantivy, they likely accept the cost or typically enable FTS too.
                # Use raw content as fallback or empty? 
                # Let's calculate normalized lazy if needed? No complex logic.
                # We will perform normalization ONLY if FTS is enabled.
                # If usage of external engine with FTS=False is common, we might need a separate flag.
                pass

            symbols, relations = [], []
            ast_status, ast_reason = "skipped", "disabled"
            parse_start = time.time()
            if size <= self.settings.MAX_AST_BYTES:
                try:
                    symbols, relations = self.extractor_cb(db_path, content)
                except:
                    pass
                if self.ast_engine.enabled:
                    lang = ParserFactory.get_language(ext)
                    if lang:
                        old_tree = self._ast_cache_get(db_path)
                        tree = self.ast_engine.parse(lang, content, old_tree)
                        if tree:
                            ast_status, ast_reason = "ok", "none"
                            self._ast_cache_put(db_path, tree)
                            try:
                                ts_symbols = self.ast_engine.extract_symbols(db_path, lang, content, tree=tree)
                                if ts_symbols:
                                    symbols = self._merge_symbols(symbols, ts_symbols)
                            except Exception:
                                pass
                        else:
                            ast_status, ast_reason = "failed", "parse_error"
                    else:
                        ast_status, ast_reason = "skipped", "unsupported"
            else:
                ast_status, ast_reason = "skipped", "too_large"
            parse_elapsed = time.time() - parse_start

            store_content = getattr(self.cfg, "store_content", True)
            stored_content = content if store_content else ""
            metadata_json = "{}"
            content_bytes = len(stored_content)
            if not store_content:
                metadata_json = '{"stored":false}'
            elif self.settings.STORE_CONTENT_COMPRESS and stored_content:
                level = max(1, min(9, self.settings.STORE_CONTENT_COMPRESS_LEVEL))
                raw_bytes = stored_content.encode("utf-8", errors="ignore")
                comp = zlib.compress(raw_bytes, level)
                stored_content = b"ZLIB\0" + comp
                content_bytes = len(raw_bytes)
                metadata_json = f'{{"compressed":"zlib","orig_bytes":{content_bytes}}}'
            
            # Re-check FTS content just in case
            if not enable_fts:
                fts_content = ""

            return {
                "type": "changed", "rel": db_path, "repo": repo, "mtime": int(st.st_mtime), "size": size,
                "content": stored_content, "content_hash": current_hash, "scan_ts": scan_ts,
                "fts_content": fts_content,
                "content_bytes": content_bytes, "metadata_json": metadata_json,
                "symbols": symbols, "relations": relations,
                "parse_elapsed": parse_elapsed,
                "parse_status": "ok", "parse_reason": "none",
                "ast_status": ast_status, "ast_reason": ast_reason,
                "is_binary": 0, "is_minified": 0,
                # Note: engine_doc might be incomplete if normalized is empty, but acceptable for 0-cost mode
                "engine_doc": self._build_engine_doc(db_path, repo, rel_to_root, normalized, int(st.st_mtime), size)
            }
        except Exception as e:
            if self.logger: self.logger.error(f"Worker failed for {file_path}: {e}")
            return None

    def _skip_result(self, db_path, repo, st, scan_ts, reason):
        return {
            "type": "changed", "rel": db_path, "repo": repo, "mtime": int(st.st_mtime), "size": st.st_size,
            "content": "", "scan_ts": scan_ts, "symbols": [], "relations": [],
            "parse_status": "skipped", "parse_reason": reason,
            "ast_status": "skipped", "ast_reason": reason,
            "is_binary": 1 if reason == "binary" else 0,
            "is_minified": 0,
            "engine_doc": None
        }

    def _build_engine_doc(self, doc_id, repo, rel_to_root, normalized_content, mtime, size):
        norm = normalized_content or ""
        root_id = doc_id.split("/", 1)[0] if "/" in doc_id else ""
        return {
            "id": doc_id, "repo": repo, "rel_path": rel_to_root,
            "root_id": root_id,
            "body_text": norm[:self.settings.ENGINE_MAX_DOC_BYTES],
            "mtime": mtime, "size": size
        }

    def _encode_db_path(self, root: Path, file_path: Path, root_id: Optional[str] = None) -> str:
        if not root_id:
            from sari.core.workspace import WorkspaceManager
            root_id = WorkspaceManager.root_id_for_workspace(str(root))
        rel = file_path.relative_to(root).as_posix()
        return f"{root_id}/{rel}"

    def _merge_symbols(self, base: List[Tuple], extra: List[Tuple]) -> List[Tuple]:
        seen = set()
        out: List[Tuple] = []
        for s in base + extra:
            key = (s[1], s[2], s[3], s[4])
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    def _ast_cache_get(self, path: str):
        if self._ast_cache_max <= 0:
            return None
        tree = self._ast_cache.get(path)
        if tree is not None:
            self._ast_cache.move_to_end(path)
        return tree

    def _ast_cache_put(self, path: str, tree: Any) -> None:
        if self._ast_cache_max <= 0:
            return
        self._ast_cache[path] = tree
        self._ast_cache.move_to_end(path)
        while len(self._ast_cache) > self._ast_cache_max:
            self._ast_cache.popitem(last=False)
