import sqlite3
import threading
import time
import zlib
import unicodedata
import os
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple, List, Dict

# Support both `python3 app/db.py` (script mode) and package mode.
try:
    from .models import SearchHit, SearchOptions
    from .ranking import get_file_extension, glob_to_like
    from .engine_registry import get_registry
    from .cjk import has_cjk as _has_cjk, cjk_space as _cjk_space_impl
except ImportError:
    from models import SearchHit, SearchOptions
    from ranking import get_file_extension, glob_to_like
    from engine_registry import get_registry
    from cjk import has_cjk as _has_cjk, cjk_space as _cjk_space_impl

def _compress(text: str) -> bytes:
    if not text: return b""
    return zlib.compress(text.encode("utf-8"), level=6)

def _decompress(data: Any) -> str:
    if not data: return ""
    if isinstance(data, str): return data # legacy
    try:
        return zlib.decompress(data).decode("utf-8")
    except Exception:
        return str(data)


def _normalize_engine_text(text: str) -> str:
    if not text:
        return ""
    norm = unicodedata.normalize("NFKC", text)
    norm = norm.lower()
    norm = " ".join(norm.split())
    return norm


def _cjk_space(text: str) -> str:
    return _cjk_space_impl(text)

def _symbol_id_for(path: str, kind: str, qualname: str) -> str:
    import hashlib
    base = f"{path}|{kind}|{qualname}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

class LocalSearchDB:
    """SQLite + optional FTS5 backed index.

    Design goals:
    - Low IO overhead: batch writes, WAL.
    - Thread safety: separate read/write connections.
    - Safer defaults: DB stored under user cache dir by default.

     enhancements:
    - File type filtering
    - Path pattern matching (glob)
    - Exclude patterns
    - Recency boost
    - Regex search mode
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Separate connections: writer (indexer) and reader (HTTP).
        self._write = sqlite3.connect(db_path, check_same_thread=False)
        self._write.row_factory = sqlite3.Row
        self._writer_thread_id: Optional[int] = None
        self._read_local = threading.local()
        self._read_conns: Dict[int, sqlite3.Connection] = {}
        self._read_conns_lock = threading.Lock()
        self._read_pool_max = int(os.environ.get("SARI_READ_POOL_MAX", "32") or 32)

        # Register decompression function
        self._write.create_function("SARI_decompress", 1, _decompress)

        self._lock = threading.Lock()

        self._apply_pragmas(self._write)
        self._read = self._open_read_connection()
        self._read_local.conn = self._read
        self._read_conns[threading.get_ident()] = self._read

        self._fts_enabled = self._try_enable_fts(self._write)
        self._init_schema()

        # TTL Cache for stats
        self._stats_cache: dict[str, Any] = {}
        self._stats_cache_ts = 0.0
        self._stats_cache_ttl = 60.0 # 60 seconds

        self.engine = get_registry().create("sqlite", self)

    def set_engine(self, engine: Any) -> None:
        self.engine = engine

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        # conn.execute("PRAGMA foreign_keys=ON;") # Disabled for compatibility with legacy extraction-only tests
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA busy_timeout=2000;")
        conn.execute("PRAGMA cache_size=-20000;")

    def _open_read_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.create_function("SARI_decompress", 1, _decompress)
        self._apply_pragmas(conn)
        try:
            conn.execute("PRAGMA query_only=ON;")
        except Exception:
            pass
        return conn

    def get_read_connection(self) -> sqlite3.Connection:
        conn = getattr(self._read_local, "conn", None)
        if conn is not None:
            return conn
        with self._read_conns_lock:
            if self._read_pool_max > 0 and len(self._read_conns) >= self._read_pool_max:
                return self._read
        conn = self._open_read_connection()
        self._read_local.conn = conn
        with self._read_conns_lock:
            self._read_conns[threading.get_ident()] = conn
        return conn

    def register_writer_thread(self, thread_id: Optional[int]) -> None:
        self._writer_thread_id = thread_id

    def _assert_writer_thread(self) -> None:
        # If no writer thread is registered, allow direct writes (legacy/tests/scripts).
        if self._writer_thread_id is None:
            return
        if threading.get_ident() != self._writer_thread_id:
            raise RuntimeError("DB write attempted outside single-writer thread")

    def open_writer_connection(self) -> sqlite3.Connection:
        # Single-writer policy: no extra writer connections.
        raise RuntimeError("open_writer_connection is disabled under single-writer mode")

    @property
    def fts_enabled(self) -> bool:
        return self._fts_enabled

    def close(self) -> None:
        conns = set()
        conns.add(self._write)
        conns.add(self._read)
        with self._read_conns_lock:
            for c in self._read_conns.values():
                conns.add(c)
            self._read_conns.clear()
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        self._writer_thread_id = None

    # ----------------------------
    # Transaction-safe *_tx methods (no commit/rollback here)
    # ----------------------------

    def upsert_files_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]) -> int:
        rows_list = []
        for r in rows:
            r_list = list(r)
            # Pad legacy rows (path, repo, mtime, size, content, last_seen)
            if len(r_list) < 14:
                while len(r_list) < 6:
                    r_list.append(0)
                defaults = ["none", "none", "none", "none", 0, 0, 0, 0]
                r_list.extend(defaults[: (14 - len(r_list))])
            raw_content = r_list[4]
            compressed_content = _compress(raw_content)
            parse_status = str(r_list[6]) if len(r_list) > 6 else "ok"
            is_binary = int(r_list[10]) if len(r_list) > 10 else 0
            fts_content = ""
            if parse_status == "ok" and not is_binary:
                fts_content = raw_content or ""
            rows_list.append((
                r_list[0], r_list[1], r_list[2], r_list[3], compressed_content, fts_content,
                r_list[5], r_list[6], r_list[7], r_list[8], r_list[9],
                r_list[10], r_list[11], r_list[12], r_list[13]
            ))
        if not rows_list:
            return 0
        cur.executemany(
            """
            INSERT INTO files(path, repo, mtime, size, content, fts_content, last_seen, parse_status, parse_reason, ast_status, ast_reason, is_binary, is_minified, sampled, content_bytes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
              repo=excluded.repo,
              mtime=excluded.mtime,
              size=excluded.size,
              content=excluded.content,
              fts_content=excluded.fts_content,
              last_seen=excluded.last_seen,
              parse_status=excluded.parse_status,
              parse_reason=excluded.parse_reason,
              ast_status=excluded.ast_status,
              ast_reason=excluded.ast_reason,
              is_binary=excluded.is_binary,
              is_minified=excluded.is_minified,
              sampled=excluded.sampled,
              content_bytes=excluded.content_bytes
            WHERE excluded.mtime >= files.mtime;
            """,
            rows_list,
        )
        # Clear old symbols for updated paths to ensure consistency
        cur.executemany("DELETE FROM symbols WHERE path = ?", [(r[0],) for r in rows_list])
        return len(rows_list)

    def upsert_symbols_tx(self, cur: sqlite3.Cursor, symbols: Iterable[tuple]) -> int:
        if hasattr(symbols, "symbols"):
            symbols_list = list(getattr(symbols, "symbols"))
        else:
            symbols_list = list(symbols)
        if not symbols_list:
            return 0
        normalized = []
        for s in symbols_list:
            vals = list(s)
            while len(vals) < 7:
                vals.append("")
            if len(vals) < 8:
                vals.append("{}")
            if len(vals) < 9:
                vals.append("")
            path = str(vals[0]) if vals else ""
            name = str(vals[1]) if len(vals) > 1 else ""
            kind = str(vals[2]) if len(vals) > 2 else ""
            parent = str(vals[6]) if len(vals) > 6 else ""
            if len(vals) <= 9:
                qualname = f"{parent}.{name}" if parent else name
                vals.append(qualname)
            else:
                qualname = str(vals[9]) if vals[9] else (f"{parent}.{name}" if parent else name)
                vals[9] = qualname
            if len(vals) <= 10:
                vals.append(_symbol_id_for(path, kind, qualname))
            else:
                if not vals[10]:
                    vals[10] = _symbol_id_for(path, kind, qualname)
            normalized.append(tuple(vals[:11]))
        symbols_list = normalized
        paths = {s[0] for s in symbols_list}
        cur.executemany("DELETE FROM symbols WHERE path = ?", [(p,) for p in paths])
        cur.executemany(
            """
            INSERT INTO symbols(path, name, kind, line, end_line, content, parent_name, metadata, docstring, qualname, symbol_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            symbols_list,
        )
        return len(symbols_list)

    def upsert_relations_tx(self, cur: sqlite3.Cursor, relations: Iterable[tuple]) -> int:
        rels_list = list(relations)
        if not rels_list:
            return 0
        normalized = []
        for r in rels_list:
            vals = list(r)
            if len(vals) == 6:
                from_path, from_symbol, to_path, to_symbol, rel_type, line = vals
                normalized.append((from_path, from_symbol, "", to_path, to_symbol, "", rel_type, line))
                continue
            if len(vals) < 8:
                vals = vals + [""] * (8 - len(vals))
            # Heuristic: if rel_type appears at index 4 and line at index 5, shift to new order
            if len(vals) >= 8 and isinstance(vals[5], int) and isinstance(vals[4], str) and vals[4] in {"calls", "extends", "implements"}:
                from_path, from_symbol, to_path, to_symbol, rel_type, line, from_sid, to_sid = vals[:8]
                normalized.append((from_path, from_symbol, from_sid, to_path, to_symbol, to_sid, rel_type, line))
            else:
                normalized.append(tuple(vals[:8]))
        rels_list = normalized
        paths = {r[0] for r in rels_list}
        cur.executemany("DELETE FROM symbol_relations WHERE from_path = ?", [(p,) for p in paths])
        cur.executemany(
            """
            INSERT INTO symbol_relations(from_path, from_symbol, from_symbol_id, to_path, to_symbol, to_symbol_id, rel_type, line)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            rels_list,
        )
        return len(rels_list)

    def delete_path_tx(self, cur: sqlite3.Cursor, path: str) -> None:
        # Explicit delete order: relations -> symbols -> files (no FK/cascade dependency)
        cur.execute("DELETE FROM symbol_relations WHERE from_path = ? OR to_path = ?", (path, path))
        cur.execute("DELETE FROM symbols WHERE path = ?", (path,))
        cur.execute("DELETE FROM files WHERE path = ?", (path,))

    def purge_legacy_paths(self, prefix: str = "root-") -> int:
        """
        Remove legacy file paths that don't match the new root_id/rel format.
        New format: root-<hash>/relative/path
        """
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            rows = cur.execute(
                "SELECT path FROM files WHERE path NOT LIKE ?",
                (f"{prefix}%/%",),
            ).fetchall()
            paths = [r[0] for r in rows]
            for p in paths:
                self.delete_path_tx(cur, p)
            self._write.commit()
        return len(paths)

    def update_last_seen_tx(self, cur: sqlite3.Cursor, paths: Iterable[str], timestamp: int) -> int:
        paths_list = list(paths)
        if not paths_list:
            return 0
        cur.executemany(
            "UPDATE files SET last_seen=? WHERE path=?",
            [(timestamp, p) for p in paths_list],
        )
        return len(paths_list)

    def upsert_repo_meta_tx(self, cur: sqlite3.Cursor, repo_name: str, tags: str = "", domain: str = "", description: str = "", priority: int = 0) -> None:
        cur.execute(
            """
            INSERT OR REPLACE INTO repo_meta (repo_name, tags, domain, description, priority)
            VALUES (?, ?, ?, ?, ?)
            """,
            (repo_name, tags, domain, description, priority)
        )

    def get_unseen_paths(self, timestamp_limit: int) -> list[str]:
        conn = self.get_read_connection()
        rows = conn.execute(
            "SELECT path FROM files WHERE last_seen < ?",
            (timestamp_limit,),
        ).fetchall()
        return [str(r["path"]) for r in rows]

    def upsert_failed_tasks_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]) -> int:
        rows_list = [list(r) for r in rows]
        if not rows_list:
            return 0
        normalized = []
        for r in rows_list:
            while len(r) < 5:
                r.append(0)
            normalized.append(tuple(r[:5]))
        cur.executemany(
            """
            INSERT INTO failed_tasks(path, attempts, last_error, last_error_ts, next_retry_ts)
            VALUES(?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
              attempts=excluded.attempts,
              last_error=excluded.last_error,
              last_error_ts=excluded.last_error_ts,
              next_retry_ts=excluded.next_retry_ts;
            """,
            normalized,
        )
        return len(normalized)

    def clear_failed_tasks_tx(self, cur: sqlite3.Cursor, paths: Iterable[str]) -> int:
        paths_list = [p for p in paths if p]
        if not paths_list:
            return 0
        cur.executemany("DELETE FROM failed_tasks WHERE path = ?", [(p,) for p in paths_list])
        return len(paths_list)

    def list_failed_tasks_ready(self, now_ts: int, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self.get_read_connection()
        rows = conn.execute(
            """
            SELECT path, attempts, last_error, last_error_ts, next_retry_ts
            FROM failed_tasks
            WHERE next_retry_ts <= ?
            ORDER BY next_retry_ts ASC
            LIMIT ?;
            """,
            (int(now_ts), int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_failed_tasks(self) -> tuple[int, int]:
        conn = self.get_read_connection()
        row = conn.execute("SELECT COUNT(*) AS c FROM failed_tasks").fetchone()
        total = int(row["c"]) if row else 0
        row2 = conn.execute("SELECT COUNT(*) AS c FROM failed_tasks WHERE attempts >= 3").fetchone()
        high = int(row2["c"]) if row2 else 0
        return total, high

    def _try_enable_fts(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __fts_test USING fts5(x)")
            conn.execute("DROP TABLE IF EXISTS __fts_test")
            return True
        except Exception:
            return False

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._write.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                  path TEXT PRIMARY KEY,
                  repo TEXT NOT NULL,
                  mtime INTEGER NOT NULL,
                  size INTEGER NOT NULL,
                  content BLOB NOT NULL,
                  fts_content TEXT DEFAULT '',
                  last_seen INTEGER DEFAULT 0,
                  parse_status TEXT NOT NULL DEFAULT 'none',
                  parse_reason TEXT NOT NULL DEFAULT 'none',
                  ast_status TEXT NOT NULL DEFAULT 'none',
                  ast_reason TEXT NOT NULL DEFAULT 'none',
                  is_binary INTEGER NOT NULL DEFAULT 0,
                  is_minified INTEGER NOT NULL DEFAULT 0,
                  sampled INTEGER NOT NULL DEFAULT 0,
                  content_bytes INTEGER NOT NULL DEFAULT 0
                );
                """
            )


            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS repo_meta (
                  repo_name TEXT PRIMARY KEY,
                  tags TEXT,
                  domain TEXT,
                  description TEXT,
                  priority INTEGER DEFAULT 0
                );
                """
            )

            # Symbols table for code intelligence
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                  path TEXT NOT NULL,
                  name TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  line INTEGER NOT NULL,
                  end_line INTEGER NOT NULL,
                  content TEXT NOT NULL,
                  parent_name TEXT DEFAULT '',
                  metadata TEXT DEFAULT '{}',
                  docstring TEXT DEFAULT '',
                  qualname TEXT DEFAULT '',
                  symbol_id TEXT DEFAULT '',
                  FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
                );
                """
            )
            # /Migration for symbols table
            try:
                cur.execute("ALTER TABLE symbols ADD COLUMN end_line INTEGER DEFAULT 0")
            except sqlite3.OperationalError: pass
            try:
                cur.execute("ALTER TABLE symbols ADD COLUMN parent_name TEXT DEFAULT ''")
            except sqlite3.OperationalError: pass
            try:
                cur.execute("ALTER TABLE symbols ADD COLUMN metadata TEXT DEFAULT '{}'")
            except sqlite3.OperationalError: pass
            try:
                cur.execute("ALTER TABLE symbols ADD COLUMN docstring TEXT DEFAULT ''")
            except sqlite3.OperationalError: pass
            try:
                cur.execute("ALTER TABLE symbols ADD COLUMN qualname TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE symbols ADD COLUMN symbol_id TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            # Symbol Relations table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_relations (
                    from_path TEXT NOT NULL,
                    from_symbol TEXT NOT NULL,
                    from_symbol_id TEXT DEFAULT '',
                    to_path TEXT NOT NULL,
                    to_symbol TEXT NOT NULL,
                    to_symbol_id TEXT DEFAULT '',
                    rel_type TEXT NOT NULL, -- 'calls', 'implements', 'extends'
                    line INTEGER NOT NULL,
                    FOREIGN KEY(from_path) REFERENCES files(path) ON DELETE CASCADE
                );
                """
            )
            try:
                cur.execute("ALTER TABLE symbol_relations ADD COLUMN from_symbol_id TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE symbol_relations ADD COLUMN to_symbol_id TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);")
            try:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_qual ON symbols(qualname);")
            except sqlite3.OperationalError:
                # Defensive migration for legacy DBs missing qualname column.
                try:
                    cur.execute("ALTER TABLE symbols ADD COLUMN qualname TEXT DEFAULT ''")
                except sqlite3.OperationalError:
                    pass
                cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_qual ON symbols(qualname);")
            try:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_sid ON symbols(symbol_id);")
            except sqlite3.OperationalError:
                # Defensive migration for legacy DBs missing symbol_id column.
                try:
                    cur.execute("ALTER TABLE symbols ADD COLUMN symbol_id TEXT DEFAULT ''")
                except sqlite3.OperationalError:
                    pass
                cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_sid ON symbols(symbol_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_from ON symbol_relations(from_symbol);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_to ON symbol_relations(to_symbol);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_from_sid ON symbol_relations(from_symbol_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_to_sid ON symbol_relations(to_symbol_id);")

            # Index for efficient filtering
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_repo ON files(repo);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime DESC);")

            # Migration for existing users
            try:
                cur.execute("ALTER TABLE files ADD COLUMN last_seen INTEGER DEFAULT 0")
                self._write.commit()
            except sqlite3.OperationalError:
                # Column already exists or table doesn't exist yet
                pass

            # 3-stage collection columns
            for stmt in [
                "ALTER TABLE files ADD COLUMN parse_status TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN parse_reason TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN ast_status TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN ast_reason TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN is_binary INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN is_minified INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN sampled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN content_bytes INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN fts_content TEXT DEFAULT ''",
            ]:
                try:
                    cur.execute(stmt)
                except sqlite3.OperationalError:
                    pass

            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_last_seen ON files(last_seen);")

            # --- Knowledge Store (Snippets / Context) ---
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS snippets (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tag TEXT NOT NULL,
                  path TEXT NOT NULL,
                  start_line INTEGER NOT NULL,
                  end_line INTEGER NOT NULL,
                  content TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  anchor_before TEXT DEFAULT '',
                  anchor_after TEXT DEFAULT '',
                  repo TEXT DEFAULT '',
                  root_id TEXT DEFAULT '',
                  note TEXT DEFAULT '',
                  commit_hash TEXT DEFAULT '',
                  created_ts INTEGER NOT NULL,
                  updated_ts INTEGER NOT NULL
                );
                """
            )
            try:
                cur.execute("ALTER TABLE snippets ADD COLUMN anchor_before TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE snippets ADD COLUMN anchor_after TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_snippets_unique
                ON snippets(tag, path, start_line, end_line);
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_snippets_tag ON snippets(tag);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_snippets_path ON snippets(path);")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS snippet_versions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  snippet_id INTEGER NOT NULL,
                  content TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  start_line INTEGER NOT NULL,
                  end_line INTEGER NOT NULL,
                  created_ts INTEGER NOT NULL,
                  FOREIGN KEY(snippet_id) REFERENCES snippets(id) ON DELETE CASCADE
                );
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_snippet_versions_sid ON snippet_versions(snippet_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_snippet_versions_hash ON snippet_versions(content_hash);")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS contexts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  topic TEXT NOT NULL UNIQUE,
                  content TEXT NOT NULL,
                  tags_json TEXT DEFAULT '[]',
                  related_files_json TEXT DEFAULT '[]',
                  source TEXT DEFAULT '',
                  valid_from INTEGER DEFAULT 0,
                  valid_until INTEGER DEFAULT 0,
                  deprecated INTEGER DEFAULT 0,
                  created_ts INTEGER NOT NULL,
                  updated_ts INTEGER NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS failed_tasks (
                  path TEXT PRIMARY KEY,
                  attempts INTEGER NOT NULL DEFAULT 0,
                  last_error TEXT DEFAULT '',
                  last_error_ts INTEGER DEFAULT 0,
                  next_retry_ts INTEGER DEFAULT 0
                );
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_failed_tasks_retry ON failed_tasks(next_retry_ts);")
            for stmt in [
                "ALTER TABLE contexts ADD COLUMN source TEXT DEFAULT ''",
                "ALTER TABLE contexts ADD COLUMN valid_from INTEGER DEFAULT 0",
                "ALTER TABLE contexts ADD COLUMN valid_until INTEGER DEFAULT 0",
                "ALTER TABLE contexts ADD COLUMN deprecated INTEGER DEFAULT 0",
            ]:
                try:
                    cur.execute(stmt)
                except sqlite3.OperationalError:
                    pass
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contexts_topic ON contexts(topic);")

            # +: FTS uses uncompressed content to avoid query-time decompression
            try:
                cur.execute(
                    "UPDATE files SET fts_content = SARI_decompress(content) "
                    "WHERE (fts_content IS NULL OR fts_content = '') AND content IS NOT NULL"
                )
                self._write.commit()
            except Exception:
                pass
            cur.execute(
                """
                DROP VIEW IF EXISTS files_view;
                """
            )
            cur.execute(
                """
                CREATE VIEW files_view AS
                SELECT rowid, path, repo, fts_content AS content
                FROM files;
                """
            )

            if self._fts_enabled:
                # Drop old FTS if it exists to ensure new schema
                # But only if it's not already using the VIEW to avoid unnecessary drops.
                # For safety in this update, we'll try to migrate.
                try:
                    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(path, repo, content, content='files_view', content_rowid='rowid')")
                except sqlite3.OperationalError:
                    # If already exists with different schema, we might need to drop/recreate.
                    # This is a one-time migration cost.
                    cur.execute("DROP TABLE IF EXISTS files_fts")
                    cur.execute("CREATE VIRTUAL TABLE files_fts USING fts5(path, repo, content, content='files_view', content_rowid='rowid')")

                cur.execute("DROP TRIGGER IF EXISTS files_ai")
                cur.execute("DROP TRIGGER IF EXISTS files_ad")
                cur.execute("DROP TRIGGER IF EXISTS files_au")

                cur.execute(
                    """
                    CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
                      INSERT INTO files_fts(rowid, path, repo, content)
                      VALUES (new.rowid, new.path, new.repo, new.fts_content);
                    END;
                    """
                )
                cur.execute(
                    """
                    CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
                      INSERT INTO files_fts(files_fts, rowid, path, repo, content)
                      VALUES('delete', old.rowid, old.path, old.repo, old.fts_content);
                    END;
                    """
                )
                cur.execute(
                    """
                    CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
                      INSERT INTO files_fts(files_fts, rowid, path, repo, content)
                      VALUES('delete', old.rowid, old.path, old.repo, old.fts_content);
                      INSERT INTO files_fts(rowid, path, repo, content)
                      VALUES (new.rowid, new.path, new.repo, new.fts_content);
                    END;
                    """
                )

    def upsert_files(self, rows: Iterable[tuple[str, str, int, int, str, int]]) -> int:
        rows_list = list(rows)
        if not rows_list:
            return 0
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            count = self.upsert_files_tx(cur, rows_list)
            self._write.commit()
        return count

    def upsert_symbols(self, symbols: Iterable[tuple]) -> int:
        """Upsert detected symbols (path, name, kind, line, end_line, content, parent_name, metadata, docstring)."""
        symbols_list = list(getattr(symbols, "symbols", symbols))
        if not symbols_list:
            return 0
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            count = self.upsert_symbols_tx(cur, symbols_list)
            self._write.commit()
        return count

    def get_symbol_block(self, path: str, name: str) -> Optional[dict[str, Any]]:
        """Get the full content block for a specific symbol ."""
        sql = """
            SELECT s.line, s.end_line, s.metadata, s.docstring, f.content
            FROM symbols s
            JOIN files f ON s.path = f.path
            WHERE s.path = ? AND s.name = ?
            ORDER BY s.line ASC
            LIMIT 1
        """
        conn = self.get_read_connection()
        row = conn.execute(sql, (path, name)).fetchone()

        if not row:
            return None

        line_start = row["line"]
        line_end = row["end_line"]
        full_content = _decompress(row["content"])

        # Extract lines
        lines = full_content.splitlines()

        # 1-based index to 0-based
        if line_end <= 0: # fallback if end_line not parsed
             line_end = line_start + 10

        start_idx = max(0, line_start - 1)
        end_idx = min(len(lines), line_end)

        block = "\n".join(lines[start_idx:end_idx])
        return {
            "name": name,
            "start_line": line_start,
            "end_line": line_end,
            "content": block,
            "metadata": row["metadata"],
            "docstring": row["docstring"]
        }

    def upsert_relations(self, relations: Iterable[tuple]) -> int:
        """Upsert symbol relations (from_path, from_symbol, from_symbol_id, to_path, to_symbol, to_symbol_id, rel_type, line)."""
        rels_list = list(relations)
        if not rels_list:
            return 0
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            count = self.upsert_relations_tx(cur, rels_list)
            self._write.commit()
        return count

    def update_last_seen(self, paths: Iterable[str], timestamp: int) -> int:
        """Update last_seen timestamp for existing files ."""
        paths_list = list(paths)
        if not paths_list:
            return 0
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            count = self.update_last_seen_tx(cur, paths_list, timestamp)
            self._write.commit()
        return count

    def delete_unseen_files(self, timestamp_limit: int) -> int:
        """Delete files that were not seen in the latest scan ."""
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            # Cascade delete should handle symbols if FK is enabled, but sqlite default often disabled.
            # Manually delete symbols for cleanliness or rely on trigger?
            # Safest to delete manually if FKs aren't reliable.
            # Let's check keys.
            cur.execute("PRAGMA foreign_keys = ON;")

            cur.execute("DELETE FROM files WHERE last_seen < ?", (timestamp_limit,))
            count = cur.rowcount
            self._write.commit()
            return count

    def delete_files(self, paths: Iterable[str]) -> int:
        paths_list = list(paths)
        if not paths_list:
            return 0
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            cur.execute("PRAGMA foreign_keys = ON;")
            cur.executemany("DELETE FROM files WHERE path=?", [(p,) for p in paths_list])
            self._write.commit()
        return len(paths_list)

    def get_all_file_paths(self) -> set[str]:
        """Get all indexed file paths for deletion detection."""
        conn = self.get_read_connection()
        rows = conn.execute("SELECT path FROM files").fetchall()
        return {r["path"] for r in rows}

    def get_file_meta(self, path: str) -> Optional[tuple[int, int]]:
        conn = self.get_read_connection()
        row = conn.execute("SELECT mtime, size FROM files WHERE path=?", (path,)).fetchone()
        if not row:
            return None
        return int(row["mtime"]), int(row["size"])

    def get_index_status(self) -> dict[str, Any]:
        """Get index metadata for debugging/UI ."""
        conn = self.get_read_connection()
        row = conn.execute("SELECT COUNT(1) AS c, MAX(mtime) AS last_mtime FROM files").fetchone()
        count = int(row["c"]) if row and row["c"] else 0
        last_mtime = int(row["last_mtime"]) if row and row["last_mtime"] else 0

        return {
            "total_files": count,
            "last_scan_time": last_mtime,
            "db_size_bytes": Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0
        }

    def has_legacy_paths(self) -> bool:
        """Return True if DB contains non root-id paths."""
        cache_key = "legacy_paths"
        now = time.time()
        cached = self._stats_cache.get(cache_key)
        if cached is not None and (now - self._stats_cache_ts < self._stats_cache_ttl):
            return bool(cached)
        try:
            conn = self.get_read_connection()
            row = conn.execute(
                "SELECT 1 AS c FROM files WHERE path NOT LIKE ? LIMIT 1",
                ("root-%/%",),
            ).fetchone()
            exists = bool(row)
            self._stats_cache[cache_key] = exists
            self._stats_cache_ts = now
            return exists
        except Exception:
            return False

    def count_files(self) -> int:
        conn = self.get_read_connection()
        row = conn.execute("SELECT COUNT(1) AS c FROM files").fetchone()
        return int(row["c"]) if row else 0

    def clear_stats_cache(self) -> None:
        """Invalidate stats cache."""
        self._stats_cache.clear()
        self._stats_cache_ts = 0.0

    def get_repo_stats(self, force_refresh: bool = False, root_ids: Optional[list[str]] = None) -> dict[str, int]:
        """Get file counts per repo with TTL cache ."""
        now = time.time()
        if root_ids:
            force_refresh = True
        if not force_refresh and (now - self._stats_cache_ts < self._stats_cache_ttl):
            cached = self._stats_cache.get("repo_stats")
            if cached is not None:
                return cached

        try:
            conn = self.get_read_connection()
            if root_ids:
                root_clauses = " OR ".join(["path LIKE ?"] * len(root_ids))
                sql = f"SELECT repo, COUNT(1) as c FROM files WHERE {root_clauses} GROUP BY repo"
                params = [f"{rid}/%" for rid in root_ids]
                rows = conn.execute(sql, params).fetchall()
            else:
                rows = conn.execute("SELECT repo, COUNT(1) as c FROM files GROUP BY repo").fetchall()
            stats = {r["repo"]: r["c"] for r in rows}
            self._stats_cache["repo_stats"] = stats
            self._stats_cache_ts = now
            return stats
        except Exception:
            return {}

    def upsert_repo_meta(self, repo_name: str, tags: str = "", domain: str = "", description: str = "", priority: int = 0) -> None:
        """Upsert repository metadata ."""
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            self.upsert_repo_meta_tx(cur, repo_name, tags, domain, description, priority)
            self._write.commit()

    def get_repo_meta(self, repo_name: str) -> Optional[dict[str, Any]]:
        """Get metadata for a specific repo."""
        conn = self.get_read_connection()
        row = conn.execute("SELECT * FROM repo_meta WHERE repo_name = ?", (repo_name,)).fetchone()
        return dict(row) if row else None

    def get_all_repo_meta(self) -> dict[str, dict[str, Any]]:
        """Get all repo metadata as a map."""
        conn = self.get_read_connection()
        rows = conn.execute("SELECT * FROM repo_meta").fetchall()
        return {row["repo_name"]: dict(row) for row in rows}

    def delete_file(self, path: str) -> None:
        """Delete a file and its symbols by path ."""
        self._assert_writer_thread()
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            self.delete_path_tx(cur, path)
            self._write.commit()

    def list_files(
        self,
        repo: Optional[str] = None,
        path_pattern: Optional[str] = None,
        file_types: Optional[list[str]] = None,
        include_hidden: bool = False,
        limit: int = 100,
        offset: int = 0,
        root_ids: Optional[list[str]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """List indexed files for debugging ."""
        limit = min(int(limit), 500)
        offset = max(int(offset), 0)

        where_clauses = []
        params: list[Any] = []

        # 0. Root filter
        if root_ids:
            root_clauses = []
            for rid in root_ids:
                root_clauses.append("f.path LIKE ?")
                params.append(f"{rid}/%")
            if root_clauses:
                where_clauses.append("(" + " OR ".join(root_clauses) + ")")

        # 1. Repo filter
        if repo:
            where_clauses.append("f.repo = ?")
            params.append(repo)

        # 2. Hidden files filter
        if not include_hidden:
            where_clauses.append("f.path NOT LIKE '%/.%'")
            where_clauses.append("f.path NOT LIKE '.%'")

        # 3. File types filter
        if file_types:
            type_clauses = []
            for ft in file_types:
                ext = ft.lower().lstrip(".")
                type_clauses.append("f.path LIKE ?")
                params.append(f"%.{ext}")
            if type_clauses:
                where_clauses.append("(" + " OR ".join(type_clauses) + ")")

        # 4. Path pattern filter
        if path_pattern:
            sql_pattern = glob_to_like(path_pattern)
            where_clauses.append("f.path LIKE ?")
            params.append(sql_pattern)

        where = " AND ".join(where_clauses) if where_clauses else "1=1"

        sql = f"""
            SELECT f.repo AS repo,
                   f.path AS path,
                   f.mtime AS mtime,
                   f.size AS size
            FROM files f
            WHERE {where}
            ORDER BY f.repo, f.path
            LIMIT ? OFFSET ?;
        """

        # Data query params
        data_params = params + [limit, offset]

        conn = self.get_read_connection()
        rows = conn.execute(sql, data_params).fetchall()

        files: list[dict[str, Any]] = []
        for r in rows:
            files.append({
                "repo": r["repo"],
                "path": r["path"],
                "mtime": int(r["mtime"]),
                "size": int(r["size"]),
                "file_type": get_file_extension(r["path"]),
            })

        # Count query params (no limit/offset)
        count_sql = f"SELECT COUNT(1) AS c FROM files f WHERE {where}"

        repo_where = where if where else "1=1"
        repo_sql = f"""
            SELECT repo, COUNT(1) AS file_count
            FROM files f
            WHERE {repo_where}
            GROUP BY repo
            ORDER BY file_count DESC;
        """
        conn = self.get_read_connection()
        count_res = conn.execute(count_sql, params).fetchone()
        total = count_res["c"] if count_res else 0
        repo_rows = conn.execute(repo_sql, params).fetchall()

        repos = [{"repo": r["repo"], "file_count": r["file_count"]} for r in repo_rows]

        meta = {
            "total": total,
            "returned": len(files),
            "offset": offset,
            "limit": limit,
            "repos": repos,
            "include_hidden": include_hidden,
        }

        return files, meta

    # ========== Helper Methods ==========

    # Delegated search logic in SearchEngine

    # ========== Main Search Methods ==========


    def search_symbols(self, query: str, repo: Optional[str] = None, limit: int = 20, root_ids: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Search for symbols by name ."""
        limit = min(limit, 100)
        query = query.strip()
        if not query:
            return []

        sql = """
            SELECT s.path, s.name, s.kind, s.line, s.end_line, s.content, s.docstring, s.metadata,
                   s.qualname, s.symbol_id, f.repo, f.mtime, f.size
            FROM symbols s
            JOIN files f ON s.path = f.path
            WHERE s.name LIKE ?
        """
        params = [f"%{query}%"]

        if root_ids:
            root_clauses = []
            for rid in root_ids:
                root_clauses.append("f.path LIKE ?")
                params.append(f"{rid}/%")
            if root_clauses:
                sql += " AND (" + " OR ".join(root_clauses) + ")"

        if repo:
            sql += " AND f.repo = ?"
            params.append(repo)

        sql += " ORDER BY length(s.name) ASC, s.path ASC LIMIT ?"
        params.append(limit)

        conn = self.get_read_connection()
        rows = conn.execute(sql, params).fetchall()

        return [
            {
                "path": r["path"],
                "repo": r["repo"],
                "name": r["name"],
                "kind": r["kind"],
                "line": r["line"],
                "snippet": r["content"],
                "docstring": r["docstring"],
                "metadata": r["metadata"],
                "qualname": r["qualname"],
                "symbol_id": r["symbol_id"],
                "mtime": int(r["mtime"]),
                "size": int(r["size"])
            }
            for r in rows
        ]

    def read_file(self, path: str) -> Optional[str]:
        """Read full file content from DB ."""
        conn = self.get_read_connection()
        row = conn.execute("SELECT content FROM files WHERE path = ?", (path,)).fetchone()
        if not row:
            return None
        content = _decompress(row["content"])
        max_bytes = int(os.environ.get("SARI_READ_MAX_BYTES", "1048576") or 1048576)
        if max_bytes > 0:
            raw = content.encode("utf-8")
            if len(raw) > max_bytes:
                clipped = raw[:max_bytes].decode("utf-8", errors="ignore")
                return clipped + f"\n\n... [CONTENT TRUNCATED (read_file bytes={len(raw)} max_bytes={max_bytes})] ..."
        return content

    def read_file_raw(self, path: str) -> Optional[str]:
        """Read full file content without read size cap (for internal tools)."""
        conn = self.get_read_connection()
        row = conn.execute("SELECT content FROM files WHERE path = ?", (path,)).fetchone()
        return _decompress(row["content"]) if row else None

    def iter_engine_documents(self, root_ids: list[str]) -> Iterable[Dict[str, Any]]:
        max_doc_bytes = int(os.environ.get("SARI_ENGINE_MAX_DOC_BYTES", "4194304") or 4194304)
        preview_bytes = int(os.environ.get("SARI_ENGINE_PREVIEW_BYTES", "8192") or 8192)
        head_bytes = max_doc_bytes // 2
        tail_bytes = max_doc_bytes - head_bytes
        conn = self.get_read_connection()
        if root_ids:
            clauses = " OR ".join(["path LIKE ?"] * len(root_ids))
            params = [f"{rid}/%" for rid in root_ids]
            sql = f"SELECT path, repo, mtime, size, content, parse_status FROM files WHERE {clauses}"
            rows = conn.execute(sql, params)
        else:
            rows = conn.execute("SELECT path, repo, mtime, size, content, parse_status FROM files")
            for r in rows:
                path = str(r["path"])
                if "/" not in path:
                    continue
                root_id, rel_path = path.split("/", 1)
                if root_ids and root_id not in root_ids:
                    continue
                path_text = f"{path} {rel_path}"
                if _has_cjk(path_text):
                    path_text = _cjk_space(path_text)
                body_text = ""
                preview = ""
                if str(r["parse_status"]) == "ok":
                    raw = _decompress(r["content"])
                    norm = _normalize_engine_text(raw)
                    if _has_cjk(norm):
                        norm = _cjk_space(norm)
                    if len(norm) > max_doc_bytes:
                        norm = norm[:head_bytes] + norm[-tail_bytes:]
                    body_text = norm
                    if preview_bytes > 0:
                        half = preview_bytes // 2
                        preview = raw[:half] + ("\n...\n" if len(raw) > preview_bytes else "") + raw[-half:]
                yield {
                    "doc_id": path,
                    "path": path,
                    "repo": str(r["repo"] or "__root__"),
                    "root_id": root_id,
                    "rel_path": rel_path,
                    "path_text": path_text,
                    "body_text": body_text,
                    "preview": preview,
                    "mtime": int(r["mtime"] or 0),
                    "size": int(r["size"] or 0),
                }

    def search_v2(self, opts: SearchOptions) -> Tuple[List[SearchHit], Dict[str, Any]]:
        return self.engine.search_v2(opts)

    # Compatibility shims for legacy tests (.x)
    def _search_like(self, opts: SearchOptions, terms: List[str],
                     meta: Dict[str, Any], no_slice: bool = False) -> Tuple[List[SearchHit], Dict[str, Any]]:
        return self.engine._search_like(opts, terms, meta, no_slice=no_slice)

    def _search_fts(self, opts: SearchOptions, terms: List[str],
                    meta: Dict[str, Any], no_slice: bool = False) -> Optional[Tuple[List[SearchHit], Dict[str, Any]]]:
        return self.engine._search_fts(opts, terms, meta, no_slice=no_slice)

    def search(
        self,
        q: str,
        repo: Optional[str],
        limit: int = 20,
        snippet_max_lines: int = 5,
        root_ids: Optional[list[str]] = None,
    ) -> Tuple[List[SearchHit], Dict[str, Any]]:
        opts = SearchOptions(
            query=q,
            repo=repo,
            limit=limit,
            snippet_lines=snippet_max_lines,
            root_ids=list(root_ids or []),
        )
        return self.search_v2(opts)

    def _get_enclosing_symbol(self, path: str, line_no: int) -> Optional[str]:
        """Find the nearest symbol definition above the given line ."""
        # Optimized query: find symbol with max line that is <= line_no
        sql = """
            SELECT kind, name
            FROM symbols
            WHERE path = ? AND line <= ?
            ORDER BY line DESC
            LIMIT 1
        """
        conn = self.get_read_connection()
        row = conn.execute(sql, (path, line_no)).fetchone()

        if row:
            return f"{row['kind']}: {row['name']}"
        return None

    def _is_exact_symbol(self, name: str) -> bool:
        """Check if a symbol with this exact name exists ."""
        conn = self.get_read_connection()
        row = conn.execute("SELECT 1 FROM symbols WHERE name = ? LIMIT 1", (name,)).fetchone()
        return bool(row)

    def repo_candidates(self, q: str, limit: int = 3, root_ids: Optional[list[str]] = None) -> List[Dict[str, Any]]:
        return self.engine.repo_candidates(q, limit, root_ids=root_ids or [])

    # ---------- Knowledge Store (Snippets / Context) ----------

    def upsert_snippet_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]) -> int:
        rows_list = [list(r) for r in rows]
        if not rows_list:
            return 0
        normalized = []
        for r in rows_list:
            # Expected: tag, path, start, end, content, hash, anchor_before, anchor_after, repo, root_id, note, commit, created_ts, updated_ts
            while len(r) < 6:
                r.append("")
            if len(r) < 8:
                r.insert(6, "")
                r.insert(7, "")
            if len(r) < 12:
                while len(r) < 12:
                    r.append("")
            if len(r) < 14:
                now = int(time.time())
                r.append(now)
                r.append(now)
            normalized.append(tuple(r[:14]))
        rows_list = normalized
        for r in rows_list:
            tag, path, start_line, end_line = r[0], r[1], r[2], r[3]
            row = cur.execute(
                """
                SELECT id, content, content_hash, start_line, end_line
                FROM snippets WHERE tag = ? AND path = ? AND start_line = ? AND end_line = ?
                """,
                (tag, path, start_line, end_line),
            ).fetchone()
            if row and row["content_hash"] != r[5]:
                cur.execute(
                    """
                    INSERT INTO snippet_versions(snippet_id, content, content_hash, start_line, end_line, created_ts)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (row["id"], row["content"], row["content_hash"], row["start_line"], row["end_line"], int(time.time())),
                )
        cur.executemany(
            """
            INSERT INTO snippets(tag, path, start_line, end_line, content, content_hash, anchor_before, anchor_after, repo, root_id, note, commit_hash, created_ts, updated_ts)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tag, path, start_line, end_line) DO UPDATE SET
              content=excluded.content,
              content_hash=excluded.content_hash,
              anchor_before=excluded.anchor_before,
              anchor_after=excluded.anchor_after,
              repo=excluded.repo,
              root_id=excluded.root_id,
              note=excluded.note,
              commit_hash=excluded.commit_hash,
              updated_ts=excluded.updated_ts;
            """,
            rows_list,
        )
        return len(rows_list)

    def upsert_context_tx(self, cur: sqlite3.Cursor, rows: Iterable[tuple]) -> int:
        rows_list = [list(r) for r in rows]
        if not rows_list:
            return 0
        normalized = []
        for r in rows_list:
            while len(r) < 4:
                r.append("")
            if len(r) < 8:
                # source, valid_from, valid_until, deprecated
                r.insert(4, "")
                r.insert(5, 0)
                r.insert(6, 0)
                r.insert(7, 0)
            if len(r) < 10:
                now = int(time.time())
                while len(r) < 8:
                    r.append(0)
                r.append(now)
                r.append(now)
            normalized.append(tuple(r[:10]))
        rows_list = normalized
        cur.executemany(
            """
            INSERT INTO contexts(topic, content, tags_json, related_files_json, source, valid_from, valid_until, deprecated, created_ts, updated_ts)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(topic) DO UPDATE SET
              content=excluded.content,
              tags_json=excluded.tags_json,
              related_files_json=excluded.related_files_json,
              source=excluded.source,
              valid_from=excluded.valid_from,
              valid_until=excluded.valid_until,
              deprecated=excluded.deprecated,
              updated_ts=excluded.updated_ts;
            """,
            rows_list,
        )
        return len(rows_list)

    def list_snippets_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        conn = self.get_read_connection()
        rows = conn.execute(
            """
            SELECT id, tag, path, start_line, end_line, content, content_hash, anchor_before, anchor_after,
                   repo, root_id, note, commit_hash, created_ts, updated_ts
            FROM snippets WHERE tag = ? ORDER BY updated_ts DESC;
            """,
            (tag,),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_snippets(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self.get_read_connection()
        like_q = f"%{query}%"
        rows = conn.execute(
            """
            SELECT id, tag, path, start_line, end_line, content, content_hash, anchor_before, anchor_after,
                   repo, root_id, note, commit_hash, created_ts, updated_ts
            FROM snippets
            WHERE tag LIKE ? OR path LIKE ? OR content LIKE ? OR note LIKE ?
            ORDER BY updated_ts DESC
            LIMIT ?;
            """,
            (like_q, like_q, like_q, like_q, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_snippet_by_key(self, tag: str, path: str, start_line: int, end_line: int) -> Optional[Dict[str, Any]]:
        conn = self.get_read_connection()
        row = conn.execute(
            """
            SELECT id, tag, path, start_line, end_line, content, content_hash, anchor_before, anchor_after,
                   repo, root_id, note, commit_hash, created_ts, updated_ts
            FROM snippets WHERE tag = ? AND path = ? AND start_line = ? AND end_line = ?;
            """,
            (tag, path, start_line, end_line),
        ).fetchone()
        return dict(row) if row else None

    def insert_snippet_version_tx(self, cur: sqlite3.Cursor, row: tuple) -> None:
        cur.execute(
            """
            INSERT INTO snippet_versions(snippet_id, content, content_hash, start_line, end_line, created_ts)
            VALUES(?,?,?,?,?,?)
            """,
            row,
        )

    def update_snippet_location_tx(
        self,
        cur: sqlite3.Cursor,
        snippet_id: int,
        start_line: int,
        end_line: int,
        content: str,
        content_hash: str,
        anchor_before: str,
        anchor_after: str,
        updated_ts: int,
    ) -> None:
        row = cur.execute(
            "SELECT content, content_hash, start_line, end_line FROM snippets WHERE id = ?",
            (snippet_id,),
        ).fetchone()
        if row and row["content_hash"] != content_hash:
            cur.execute(
                """
                INSERT INTO snippet_versions(snippet_id, content, content_hash, start_line, end_line, created_ts)
                VALUES(?,?,?,?,?,?)
                """,
                (snippet_id, row["content"], row["content_hash"], row["start_line"], row["end_line"], int(time.time())),
            )
        cur.execute(
            """
            UPDATE snippets
            SET start_line = ?, end_line = ?, content = ?, content_hash = ?,
                anchor_before = ?, anchor_after = ?, updated_ts = ?
            WHERE id = ?
            """,
            (start_line, end_line, content, content_hash, anchor_before, anchor_after, updated_ts, snippet_id),
        )

    def list_snippet_versions(self, snippet_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        conn = self.get_read_connection()
        rows = conn.execute(
            """
            SELECT id, snippet_id, content, content_hash, start_line, end_line, created_ts
            FROM snippet_versions WHERE snippet_id = ? ORDER BY created_ts DESC LIMIT ?;
            """,
            (snippet_id, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_context_by_topic(self, topic: str) -> Optional[Dict[str, Any]]:
        conn = self.get_read_connection()
        row = conn.execute(
            """
            SELECT id, topic, content, tags_json, related_files_json, source, valid_from, valid_until, deprecated, created_ts, updated_ts
            FROM contexts WHERE topic = ?;
            """,
            (topic,),
        ).fetchone()
        return dict(row) if row else None

    def search_contexts(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self.get_read_connection()
        like_q = f"%{query}%"
        rows = conn.execute(
            """
            SELECT id, topic, content, tags_json, related_files_json, source, valid_from, valid_until, deprecated, created_ts, updated_ts
            FROM contexts
            WHERE topic LIKE ? OR content LIKE ? OR tags_json LIKE ? OR related_files_json LIKE ?
            ORDER BY updated_ts DESC
            LIMIT ?;
            """,
            (like_q, like_q, like_q, like_q, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
