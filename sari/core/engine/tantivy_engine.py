import os
import shutil
import threading
import time
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from sari.core.settings import settings

try:
    import tantivy
except ImportError:
    tantivy = None

class TantivyEngine:
    """
    Tantivy-based search engine for Sari.
    Unified global index with root_id filtering.
    """
    def __init__(self, index_path: str, logger=None, settings_obj=None):
        self.index_path = Path(index_path)
        self.logger = logger
        self.settings = settings_obj or settings
        self._index = None
        self._schema = None
        self._writer = None
        self._last_reload_ts = 0.0
        self._writer_lock = threading.Lock()
        self._reload_lock = threading.Lock()
        self._disabled_reason = ""
        self._tantivy = tantivy

        if tantivy:
            ver = str(getattr(tantivy, "__version__", "") or "")
            if not self._is_supported_tantivy_version(ver):
                self._disabled_reason = f"Unsupported tantivy version: {ver} (required 0.25.x)"
                if self.logger:
                    try:
                        self.logger.error(self._disabled_reason)
                    except Exception:
                        pass
                return
            self._setup_schema()
            self._init_index()

    def _is_supported_tantivy_version(self, version: str) -> bool:
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", version or "")
        if not m:
            return False
        major, minor = int(m.group(1)), int(m.group(2))
        return major == 0 and minor == 25

    def _setup_schema(self):
        schema_builder = tantivy.SchemaBuilder()
        schema_builder.add_text_field("root_id", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("path", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("repo", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("body", stored=True, tokenizer_name="en_stem")
        schema_builder.add_integer_field("mtime", stored=True, indexed=True)
        schema_builder.add_integer_field("size", stored=True, indexed=True)
        self._schema = schema_builder.build()

    def _init_index(self):
        self.index_path.mkdir(parents=True, exist_ok=True)
        try:
            self._index = tantivy.Index(self._schema, path=str(self.index_path))
        except:
            # If corrupted, re-create
            shutil.rmtree(self.index_path)
            self.index_path.mkdir(parents=True, exist_ok=True)
            self._index = tantivy.Index(self._schema, path=str(self.index_path))
        
    def upsert_documents(self, docs: List[Dict[str, Any]]):
        if not tantivy or not self._index: return
        
        with self._writer_lock:
            # Ticket 5.4: Enforce memory budget for indexing
            memory_budget = self.settings.ENGINE_INDEX_MEM_MB * 1024 * 1024
            if self._writer is None:
                self._writer = self._index.writer(memory_budget)
            writer = self._writer
            
            for d in docs:
                doc_id = d.get("doc_id") or d.get("id")
                if not doc_id:
                    continue
                if hasattr(writer, "delete_documents"):
                    writer.delete_documents("path", doc_id)
                else:
                    writer.delete_term("path", doc_id)
                writer.add_document(tantivy.Document(
                    root_id=d.get("root_id", ""),
                    path=doc_id,
                    repo=d.get("repo", ""),
                    body=d.get("body_text", ""),
                    mtime=d.get("mtime", 0),
                    size=d.get("size", 0)
                ))
            writer.commit()
            # Wait for merge to complete in a real env, but for local tool commit is enough

    def delete_documents(self, doc_ids: List[str]):
        if not tantivy or not self._index: return
        with self._writer_lock:
            if self._writer is None:
                self._writer = self._index.writer()
            writer = self._writer
            for doc_id in doc_ids:
                if hasattr(writer, "delete_documents"):
                    writer.delete_documents("path", doc_id)
                else:
                    writer.delete_term("path", doc_id)
            writer.commit()

    def close(self) -> None:
        if not tantivy:
            return
        with self._writer_lock:
            if self._writer is not None:
                try:
                    self._writer.commit()
                except Exception:
                    pass
                # Tantivy writer doesn't always have a close() method in all versions,
                # but setting it to None triggers cleanup in the binding.
                self._writer = None

    def _escape_query(self, text: str) -> str:
        if text is None:
            return ""
        # Escape Tantivy/Lucene special chars
        specials = r'+-&&||!(){}[]^"~*?:\\/'
        out = []
        for ch in text:
            if ch in specials:
                out.append("\\" + ch)
            else:
                out.append(ch)
        return "".join(out)

    def search(self, query: str, root_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if not tantivy or not self._index: return []
        
        now = time.time()
        reload_interval = max(0, self.settings.ENGINE_RELOAD_MS) / 1000.0
        
        # Reader reload uses a separate lock to avoid multiple reloads in parallel
        if reload_interval == 0 or (now - self._last_reload_ts) >= reload_interval:
            with self._reload_lock:
                # Re-check inside lock (double-checked locking pattern)
                if reload_interval == 0 or (now - self._last_reload_ts) >= reload_interval:
                    self._index.reload()
                    self._last_reload_ts = now

        searcher = self._index.searcher()
        
        # Build query: (body:query) AND (root_id:root_id)
        safe_q = self._escape_query(query or "")
        safe_root = self._escape_query(root_id or "")
        full_query = f"body:({safe_q})"
        if root_id:
            full_query = f"({full_query}) AND root_id:\"{safe_root}\""
            
        try:
            q = self._index.parse_query(full_query, ["body"])
        except Exception as e:
            if self.logger: self.logger.log_error(f"Tantivy query parse failed: {e}")
            return []
        try:
            hits = searcher.search(q, limit).hits
            
            results = []
            for score, address in hits:
                doc = searcher.doc(address)
                results.append({
                    "path": doc["path"][0],
                    "root_id": doc["root_id"][0],
                    "repo": doc["repo"][0],
                    "mtime": doc["mtime"][0],
                    "size": doc["size"][0],
                    "score": score
                })
            return results
        except Exception as e:
            if self.logger: self.logger.log_error(f"Tantivy search failed: {e}")
            return []
