import sqlite3
import threading
import time
import logging
import os
import zlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Iterable
from .schema import init_schema, CURRENT_SCHEMA_VERSION
from sari.core.settings import settings

class LocalSearchDB:
    def __init__(self, db_path: str, logger=None):
        self.db_path = db_path
        self.logger = logger or logging.getLogger("sari.db")
        self._local = threading.local()
        self._lock = threading.Lock()
        self._conns: set[sqlite3.Connection] = set()
        self._conns_lock = threading.Lock()
        self._writer_thread_id = None
        self.coordinator = None 
        self.engine = None
        self.settings = settings
        
        self._check_and_migrate()
        with self._get_conn() as conn:
            init_schema(conn)

    def _check_and_migrate(self):
        if not os.path.exists(self.db_path): return
        try:
            conn = sqlite3.connect(self.db_path)
            v = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            conn.close()
            if not v or v[0] < CURRENT_SCHEMA_VERSION:
                os.remove(self.db_path)
        except:
            try: os.remove(self.db_path)
            except: pass

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn.row_factory = sqlite3.Row
            with self._conns_lock:
                self._conns.add(self._local.conn)
        return self._local.conn

    @property
    def _write(self) -> sqlite3.Connection: return self._get_conn()

    @property
    def _read(self) -> sqlite3.Connection: return self._get_conn()

    @property
    def fts_enabled(self) -> bool:
        """Check if FTS5 is supported by the SQLite library."""
        try:
            conn = self._get_conn()
            res = conn.execute("PRAGMA compile_options").fetchall()
            options = [r[0] for r in res]
            return "ENABLE_FTS5" in options
        except Exception:
            return False

    def register_writer_thread(self, tid: Optional[int]): self._writer_thread_id = tid

    def set_engine(self, engine: Any) -> None:
        self.engine = engine

    def set_settings(self, settings_obj: Any) -> None:
        self.settings = settings_obj

    # --- Roots ---
    def upsert_root(self, root_id: str, root_path: str, real_path: str, label: str = "", config_json: str = "{}"):
        with self._lock:
            now = int(time.time())
            self._write.execute("INSERT INTO roots (root_id, root_path, real_path, label, config_json, created_ts, updated_ts) VALUES (?,?,?,?,?,?,?) ON CONFLICT(root_id) DO UPDATE SET updated_ts=excluded.updated_ts", (root_id, root_path, real_path, label, config_json, now, now))
            self._write.commit()

    def get_roots(self) -> List[Dict[str, Any]]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT root_id, root_path, real_path, label, state FROM roots")
        return [{"root_id": r[0], "root_path": r[1], "real_path": r[2], "label": r[3], "state": r[4]} for r in cur.fetchall()]

    # --- Search & Content ---
    def get_file_meta(self, path: str):
        return self._get_conn().execute("SELECT mtime, size, content_hash FROM files WHERE path = ?", (path,)).fetchone()

    def read_file(self, path: str) -> Optional[str]:
        row = self._get_conn().execute("SELECT content FROM files WHERE path = ?", (path,)).fetchone()
        if row:
            content = row[0]
            if isinstance(content, bytes):
                if content.startswith(b"ZLIB\0"):
                    try:
                        content = zlib.decompress(content[5:]).decode("utf-8", errors="ignore")
                    except Exception:
                        content = ""
                else:
                    content = content.decode("utf-8", errors="ignore")
            if content:
                return content
            # Fallback: read from disk if content not stored
            try:
                root_id, rel = path.split("/", 1)
            except ValueError:
                return content
            root_path = self._get_root_path(root_id)
            if root_path:
                full_path = Path(root_path) / rel
                if full_path.exists():
                    try:
                        return full_path.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        return content
            return content
        return None

    def _get_root_path(self, root_id: str) -> Optional[str]:
        row = self._get_conn().execute("SELECT root_path FROM roots WHERE root_id = ?", (root_id,)).fetchone()
        return row[0] if row else None

    def apply_root_filter(self, sql: str, root_id: Optional[str]) -> Tuple[str, List[Any]]:
        params = []
        if root_id:
            sql += " WHERE root_id = ?"
            params.append(root_id)
        else:
            sql += " WHERE 1=1"
        return sql, params

    def search_files(self, query: str, root_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        sql = "SELECT path, root_id, repo, mtime, size, parse_status FROM files"
        sql, params = self.apply_root_filter(sql, root_id)
        if query:
            sql += " AND (path LIKE ? OR rel_path LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        sql += " LIMIT ?"
        params.append(limit)
        cur = self._get_conn().cursor()
        cur.execute(sql, params)
        return [{"path": r[0], "root_id": r[1], "repo": r[2], "mtime": r[3], "size": r[4], "status": r[5]} for r in cur.fetchall()]

    def search_symbols(self, query: str, root_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        sql = "SELECT symbol_id, path, root_id, name, kind, line, end_line FROM symbols"
        sql, params = self.apply_root_filter(sql, root_id)
        if query:
            sql += " AND name LIKE ?"
            params.append(f"%{query}%")
        sql += " LIMIT ?"
        params.append(limit)
        cur = self._get_conn().cursor()
        cur.execute(sql, params)
        return [
            {"symbol_id": r[0], "path": r[1], "root_id": r[2], "name": r[3], "kind": r[4], "line": r[5], "end_line": r[6]}
            for r in cur.fetchall()
        ]

    def list_files(self, repo=None, path_pattern=None, file_types=None, include_hidden=False, limit=100, offset=0, root_ids=None):
        sql = "SELECT path, repo, mtime FROM files WHERE 1=1"
        params = []
        if repo: sql += " AND repo = ?"; params.append(repo)
        if root_ids:
            sql += " AND root_id IN (" + ",".join("?"*len(root_ids)) + ")"
            params.extend(root_ids)
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._get_conn().execute(sql, params).fetchall()
        return [{"path": r[0], "repo": r[1], "mtime": r[2]} for r in rows], {"total": len(rows)}

    def get_repo_stats(self, root_ids=None):
        sql = "SELECT repo, COUNT(1) FROM files"
        params = []
        if root_ids:
            sql += " WHERE root_id IN (" + ",".join("?"*len(root_ids)) + ")"
            params.extend(root_ids)
        sql += " GROUP BY repo"
        rows = self._get_conn().execute(sql, params).fetchall()
        return {r[0]: r[1] for r in rows}

    def has_legacy_paths(self): return False

    # --- Transactions ---
    def upsert_files_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]):
        cur.executemany(
            "INSERT INTO files (path, rel_path, root_id, repo, mtime, size, content, content_hash, fts_content, last_seen, deleted_ts, parse_status, parse_reason, ast_status, ast_reason, is_binary, is_minified, sampled, content_bytes, metadata_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "rel_path=excluded.rel_path, repo=excluded.repo, mtime=excluded.mtime, size=excluded.size, "
            "content=excluded.content, content_hash=excluded.content_hash, fts_content=excluded.fts_content, "
            "last_seen=excluded.last_seen, deleted_ts=excluded.deleted_ts, "
            "parse_status=excluded.parse_status, parse_reason=excluded.parse_reason, "
            "ast_status=excluded.ast_status, ast_reason=excluded.ast_reason, "
            "is_binary=excluded.is_binary, is_minified=excluded.is_minified, sampled=excluded.sampled, "
            "content_bytes=excluded.content_bytes, metadata_json=excluded.metadata_json "
            "WHERE excluded.mtime >= files.mtime", # 최신 데이터만 덮어쓰기 허용
            rows
        )
        # Clear DLQ on success
        cur.executemany("DELETE FROM failed_tasks WHERE path = ?", [(r[0],) for r in rows])

    def upsert_symbols_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]):
        cur.executemany("INSERT INTO symbols (symbol_id, path, root_id, name, kind, line, end_line, content, parent_name, metadata, docstring, qualname) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(root_id, path, name, line) DO UPDATE SET line=excluded.line", rows)

    def upsert_relations_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]):
        cur.executemany("INSERT OR IGNORE INTO symbol_relations (from_path, from_root_id, from_symbol, from_symbol_id, to_path, to_root_id, to_symbol, to_symbol_id, rel_type, line, metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    def upsert_repo_meta_tx(self, cur: sqlite3.Cursor, name: str, tags: str, domain: str, desc: str, priority: int):
        cur.execute("INSERT INTO repo_meta (repo_name, tags, domain, description, priority) VALUES (?,?,?,?,?) ON CONFLICT(repo_name) DO UPDATE SET priority=excluded.priority", (name, tags, domain, desc, priority))

    def upsert_snippet_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]):
        cur.executemany("INSERT OR IGNORE INTO snippets (tag, path, root_id, start_line, end_line, content, content_hash, anchor_before, anchor_after, repo, note, commit_hash, created_ts, updated_ts, metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    def upsert_context_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]):
        cur.executemany("INSERT INTO contexts (topic, content, tags_json, related_files_json, source, valid_from, valid_until, deprecated, created_ts, updated_ts) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(topic) DO UPDATE SET updated_ts=excluded.updated_ts", rows)

    def upsert_failed_tasks_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]):
        cur.executemany("INSERT INTO failed_tasks (path, root_id, attempts, error, ts, next_retry, metadata_json) VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET attempts=attempts+1", rows)

    def clear_failed_tasks_tx(self, cur: sqlite3.Cursor, paths: List[str]):
        cur.executemany("DELETE FROM failed_tasks WHERE path = ?", [(p,) for p in paths])

    def mark_embeddings_stale(self, cur: sqlite3.Cursor, root_id: str, path: str, hash: str):
        cur.execute("UPDATE embeddings SET status = 'stale', updated_ts = ? WHERE root_id = ? AND entity_id = ? AND content_hash != ?", (int(time.time()), root_id, path, hash))

    def prune_old_files(self, root_id: str, before_ts: int) -> int:
        """이번 스캔에서 발견되지 않은 파일을 삭제합니다. (가비지 컬렉션)"""
        with self._lock:
            # 1. 파일 삭제
            cur = self._write.cursor()
            # 삭제될 파일 목록 확보 (엔진 동기화용)
            cur.execute("SELECT path FROM files WHERE root_id = ? AND last_seen < ?", (root_id, before_ts))
            paths_to_delete = [r[0] for r in cur.fetchall()]
            
            if not paths_to_delete:
                return 0
                
            cur.execute("DELETE FROM files WHERE root_id = ? AND last_seen < ?", (root_id, before_ts))
            # 2. 관련 심볼 및 관계 삭제 (ON DELETE CASCADE가 설정되어 있지 않을 경우 대비)
            # schema.py 확인 결과 root_id 기반 연쇄 삭제가 일부 설정되어 있으나, path 기준은 명시적 처리 안전
            for p in paths_to_delete:
                cur.execute("DELETE FROM symbols WHERE path = ?", (p,))
            
            self._write.commit()
            
            # 3. 검색 엔진(Tantivy)에서도 삭제
            if self.engine and hasattr(self.engine, "delete_documents"):
                try:
                    self.engine.delete_documents(paths_to_delete)
                except: pass
                
            return len(paths_to_delete)

            return len(paths_to_delete)

    def prune_data(self, table: str, days: int) -> int:
        """Prune old data from auxiliary tables based on TTL."""
        if table not in ("snippets", "failed_tasks", "contexts"):
            return 0
            
        cutoff = int(time.time()) - (days * 86400)
        col = "ts" if table == "failed_tasks" else "updated_ts"
        
        with self._lock:
            cur = self._write.cursor()
            cur.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
            count = cur.rowcount
            self._write.commit()
            return count

    def get_failed_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get tasks eligible for retry."""
        now = int(time.time())
        try:
            cur = self._get_conn().cursor()
            cur.execute("SELECT path, root_id, attempts FROM failed_tasks WHERE next_retry <= ? LIMIT ?", (now, limit))
            return [{"path": r[0], "root_id": r[1], "attempts": r[2]} for r in cur.fetchall()]
        except Exception:
            return []

    def close(self):
        """Close the connection for the current thread."""
        if hasattr(self._local, "conn"):
            conn = self._local.conn
            try:
                conn.close()
            except Exception:
                pass
            with self._conns_lock:
                self._conns.discard(conn)
            del self._local.conn

    def close_all(self):
        """Close all tracked connections and the engine."""
        with self._conns_lock:
            conns = list(self._conns)
            self._conns.clear()
        
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        
        if self.engine and hasattr(self.engine, "close"):
            try:
                self.engine.close()
            except Exception:
                pass
