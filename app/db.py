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
except ImportError:
    from models import SearchHit, SearchOptions
    from ranking import get_file_extension, glob_to_like
    from engine_registry import get_registry

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

class LocalSearchDB:
    """SQLite + optional FTS5 backed index.

    Design goals:
    - Low IO overhead: batch writes, WAL.
    - Thread safety: separate read/write connections.
    - Safer defaults: DB stored under user cache dir by default.
    
    v2.3.1 enhancements:
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
        self._read = sqlite3.connect(db_path, check_same_thread=False)
        self._write.row_factory = sqlite3.Row
        self._read.row_factory = sqlite3.Row

        # Register decompression function (v2.7.0)
        self._write.create_function("deckard_decompress", 1, _decompress)
        self._read.create_function("deckard_decompress", 1, _decompress)

        self._lock = threading.Lock()

        self._read_lock = threading.Lock()

        self._apply_pragmas(self._write)
        self._apply_pragmas(self._read)

        self._fts_enabled = self._try_enable_fts(self._write)
        self._init_schema()
        
        # TTL Cache for stats (v2.5.1)
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

    def open_writer_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.create_function("deckard_decompress", 1, _decompress)
        self._apply_pragmas(conn)
        return conn

    @property
    def fts_enabled(self) -> bool:
        return self._fts_enabled

    def close(self) -> None:
        for c in (self._read, self._write):
            try:
                c.close()
            except Exception:
                pass

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
            compressed_content = _compress(r_list[4])
            rows_list.append((
                r_list[0], r_list[1], r_list[2], r_list[3], compressed_content,
                r_list[5], r_list[6], r_list[7], r_list[8], r_list[9],
                r_list[10], r_list[11], r_list[12], r_list[13]
            ))
        if not rows_list:
            return 0
        cur.executemany(
            """
            INSERT INTO files(path, repo, mtime, size, content, last_seen, parse_status, parse_reason, ast_status, ast_reason, is_binary, is_minified, sampled, content_bytes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
              repo=excluded.repo,
              mtime=excluded.mtime,
              size=excluded.size,
              content=excluded.content,
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
        # Clear old symbols for updated paths to ensure consistency (v2.8.0)
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
            if len(s) == 7:
                normalized.append(s + ("{}", ""))
            elif len(s) == 9:
                normalized.append(s)
            else:
                tmp = list(s) + [""] * (9 - len(s))
                normalized.append(tuple(tmp[:9]))
        symbols_list = normalized
        paths = {s[0] for s in symbols_list}
        cur.executemany("DELETE FROM symbols WHERE path = ?", [(p,) for p in paths])
        cur.executemany(
            """
            INSERT INTO symbols(path, name, kind, line, end_line, content, parent_name, metadata, docstring)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            symbols_list,
        )
        return len(symbols_list)

    def upsert_relations_tx(self, cur: sqlite3.Cursor, relations: Iterable[tuple[str, str, str, str, str, int]]) -> int:
        rels_list = list(relations)
        if not rels_list:
            return 0
        paths = {r[0] for r in rels_list}
        cur.executemany("DELETE FROM symbol_relations WHERE from_path = ?", [(p,) for p in paths])
        cur.executemany(
            """
            INSERT INTO symbol_relations(from_path, from_symbol, to_path, to_symbol, rel_type, line)
            VALUES(?,?,?,?,?,?)
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
        with self._read_lock:
            rows = self._read.execute(
                "SELECT path FROM files WHERE last_seen < ?",
                (timestamp_limit,),
            ).fetchall()
        return [str(r["path"]) for r in rows]

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

            # v2.6.0: Symbols table for code intelligence
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
                  FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
                );
                """
            )
            # v2.7.0/v2.9.0: Migration for symbols table
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

            # v2.9.0: Symbol Relations table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_relations (
                    from_path TEXT NOT NULL,
                    from_symbol TEXT NOT NULL,
                    to_path TEXT NOT NULL,
                    to_symbol TEXT NOT NULL,
                    rel_type TEXT NOT NULL, -- 'calls', 'implements', 'extends'
                    line INTEGER NOT NULL,
                    FOREIGN KEY(from_path) REFERENCES files(path) ON DELETE CASCADE
                );
                """
            )

            cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_from ON symbol_relations(from_symbol);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_to ON symbol_relations(to_symbol);")

            # Index for efficient filtering
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_repo ON files(repo);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime DESC);")
            
            # v2.5.3: Migration for existing users
            try:
                cur.execute("ALTER TABLE files ADD COLUMN last_seen INTEGER DEFAULT 0")
                self._write.commit()
            except sqlite3.OperationalError:
                # Column already exists or table doesn't exist yet
                pass

            # v2.10.0: 3-stage collection columns
            for stmt in [
                "ALTER TABLE files ADD COLUMN parse_status TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN parse_reason TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN ast_status TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN ast_reason TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE files ADD COLUMN is_binary INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN is_minified INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN sampled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN content_bytes INTEGER NOT NULL DEFAULT 0",
            ]:
                try:
                    cur.execute(stmt)
                except sqlite3.OperationalError:
                    pass

            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_last_seen ON files(last_seen);")
            
            # v2.7.0: Compressed content storage with FTS support via VIEW
            cur.execute(
                """
                CREATE VIEW IF NOT EXISTS files_view AS
                SELECT rowid, path, repo, deckard_decompress(content) AS content
                FROM files;
                """
            )
            
            if self._fts_enabled:
                # Drop old FTS if it exists to ensure new schema (v2.7.0)
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
                      VALUES (new.rowid, new.path, new.repo, deckard_decompress(new.content));
                    END;
                    """
                )
                cur.execute(
                    """
                    CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
                      INSERT INTO files_fts(files_fts, rowid, path, repo, content) 
                      VALUES('delete', old.rowid, old.path, old.repo, deckard_decompress(old.content));
                    END;
                    """
                )
                cur.execute(
                    """
                    CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
                      INSERT INTO files_fts(files_fts, rowid, path, repo, content) 
                      VALUES('delete', old.rowid, old.path, old.repo, deckard_decompress(old.content));
                      INSERT INTO files_fts(rowid, path, repo, content) 
                      VALUES (new.rowid, new.path, new.repo, deckard_decompress(new.content));
                    END;
                    """
                )

    def upsert_files(self, rows: Iterable[tuple[str, str, int, int, str, int]]) -> int:
        rows_list = list(rows)
        if not rows_list:
            return 0
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
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            count = self.upsert_symbols_tx(cur, symbols_list)
            self._write.commit()
        return count

    def get_symbol_block(self, path: str, name: str) -> Optional[dict[str, Any]]:
        """Get the full content block for a specific symbol (v2.7.0)."""
        sql = """
            SELECT s.line, s.end_line, s.metadata, s.docstring, f.content
            FROM symbols s
            JOIN files f ON s.path = f.path
            WHERE s.path = ? AND s.name = ?
            ORDER BY s.line ASC
            LIMIT 1
        """
        with self._read_lock:
            row = self._read.execute(sql, (path, name)).fetchone()
            
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

    def upsert_relations(self, relations: Iterable[tuple[str, str, str, str, str, int]]) -> int:
        """Upsert symbol relations (from_path, from_symbol, to_path, to_symbol, rel_type, line)."""
        rels_list = list(relations)
        if not rels_list:
            return 0
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            count = self.upsert_relations_tx(cur, rels_list)
            self._write.commit()
        return count

    def update_last_seen(self, paths: Iterable[str], timestamp: int) -> int:
        """Update last_seen timestamp for existing files (v2.5.3)."""
        paths_list = list(paths)
        if not paths_list:
            return 0
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            count = self.update_last_seen_tx(cur, paths_list, timestamp)
            self._write.commit()
        return count

    def delete_unseen_files(self, timestamp_limit: int) -> int:
        """Delete files that were not seen in the latest scan (v2.5.3)."""
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
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            cur.execute("PRAGMA foreign_keys = ON;")
            cur.executemany("DELETE FROM files WHERE path=?", [(p,) for p in paths_list])
            self._write.commit()
        return len(paths_list)

    def get_all_file_paths(self) -> set[str]:
        """Get all indexed file paths for deletion detection."""
        with self._read_lock:
            rows = self._read.execute("SELECT path FROM files").fetchall()
        return {r["path"] for r in rows}

    def get_file_meta(self, path: str) -> Optional[tuple[int, int]]:
        with self._read_lock:
            row = self._read.execute("SELECT mtime, size FROM files WHERE path=?", (path,)).fetchone()
        if not row:
            return None
        return int(row["mtime"]), int(row["size"])

    def get_index_status(self) -> dict[str, Any]:
        """Get index metadata for debugging/UI (v2.4.2)."""
        with self._read_lock:
            row = self._read.execute("SELECT COUNT(1) AS c, MAX(mtime) AS last_mtime FROM files").fetchone()
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
            with self._read_lock:
                row = self._read.execute(
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
        with self._read_lock:
            row = self._read.execute("SELECT COUNT(1) AS c FROM files").fetchone()
        return int(row["c"]) if row else 0

    def clear_stats_cache(self) -> None:
        """Invalidate stats cache."""
        self._stats_cache.clear()
        self._stats_cache_ts = 0.0

    def get_repo_stats(self, force_refresh: bool = False, root_ids: Optional[list[str]] = None) -> dict[str, int]:
        """Get file counts per repo with TTL cache (v2.5.1)."""
        now = time.time()
        if root_ids:
            force_refresh = True
        if not force_refresh and (now - self._stats_cache_ts < self._stats_cache_ttl):
            cached = self._stats_cache.get("repo_stats")
            if cached is not None:
                return cached

        try:
            with self._read_lock:
                if root_ids:
                    root_clauses = " OR ".join(["path LIKE ?"] * len(root_ids))
                    sql = f"SELECT repo, COUNT(1) as c FROM files WHERE {root_clauses} GROUP BY repo"
                    params = [f"{rid}/%" for rid in root_ids]
                    rows = self._read.execute(sql, params).fetchall()
                else:
                    rows = self._read.execute("SELECT repo, COUNT(1) as c FROM files GROUP BY repo").fetchall()
            stats = {r["repo"]: r["c"] for r in rows}
            self._stats_cache["repo_stats"] = stats
            self._stats_cache_ts = now
            return stats
        except Exception:
            return {}

    def upsert_repo_meta(self, repo_name: str, tags: str = "", domain: str = "", description: str = "", priority: int = 0) -> None:
        """Upsert repository metadata (v2.4.3)."""
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            self.upsert_repo_meta_tx(cur, repo_name, tags, domain, description, priority)
            self._write.commit()

    def get_repo_meta(self, repo_name: str) -> Optional[dict[str, Any]]:
        """Get metadata for a specific repo."""
        with self._read_lock:
            row = self._read.execute("SELECT * FROM repo_meta WHERE repo_name = ?", (repo_name,)).fetchone()
        return dict(row) if row else None

    def get_all_repo_meta(self) -> dict[str, dict[str, Any]]:
        """Get all repo metadata as a map."""
        with self._read_lock:
            rows = self._read.execute("SELECT * FROM repo_meta").fetchall()
        return {row["repo_name"]: dict(row) for row in rows}

    def delete_file(self, path: str) -> None:
        """Delete a file and its symbols by path (v2.7.2)."""
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
        """List indexed files for debugging (v2.4.0)."""
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
        
        with self._read_lock:
            rows = self._read.execute(sql, data_params).fetchall()
        
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
        with self._read_lock:
            count_res = self._read.execute(count_sql, params).fetchone()
            total = count_res["c"] if count_res else 0
            repo_rows = self._read.execute(repo_sql, params).fetchall()
            
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
        """Search for symbols by name (v2.6.0)."""
        limit = min(limit, 100)
        query = query.strip()
        if not query:
            return []
            
        sql = """
            SELECT s.path, s.name, s.kind, s.line, s.end_line, s.content, s.docstring, s.metadata, f.repo, f.mtime, f.size
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
        
        with self._read_lock:
            rows = self._read.execute(sql, params).fetchall()
            
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
                "mtime": int(r["mtime"]),
                "size": int(r["size"])
            }
            for r in rows
        ]

    def read_file(self, path: str) -> Optional[str]:
        """Read full file content from DB (v2.6.0)."""
        with self._read_lock:
            row = self._read.execute("SELECT content FROM files WHERE path = ?", (path,)).fetchone()
        return _decompress(row["content"]) if row else None

    def iter_engine_documents(self, root_ids: list[str]) -> Iterable[Dict[str, Any]]:
        max_doc_bytes = int(os.environ.get("DECKARD_ENGINE_MAX_DOC_BYTES", "4194304") or 4194304)
        preview_bytes = int(os.environ.get("DECKARD_ENGINE_PREVIEW_BYTES", "8192") or 8192)
        head_bytes = max_doc_bytes // 2
        tail_bytes = max_doc_bytes - head_bytes
        with self._read_lock:
            if root_ids:
                clauses = " OR ".join(["path LIKE ?"] * len(root_ids))
                params = [f"{rid}/%" for rid in root_ids]
                sql = f"SELECT path, repo, mtime, size, content, parse_status FROM files WHERE {clauses}"
                rows = self._read.execute(sql, params)
            else:
                rows = self._read.execute("SELECT path, repo, mtime, size, content, parse_status FROM files")
            for r in rows:
                path = str(r["path"])
                if "/" not in path:
                    continue
                root_id, rel_path = path.split("/", 1)
                if root_ids and root_id not in root_ids:
                    continue
                path_text = f"{path} {rel_path}"
                body_text = ""
                preview = ""
                if str(r["parse_status"]) == "ok":
                    raw = _decompress(r["content"])
                    norm = _normalize_engine_text(raw)
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

    # Compatibility shims for legacy tests (v2.7.x)
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
        """Find the nearest symbol definition above the given line (v2.6.0)."""
        # Optimized query: find symbol with max line that is <= line_no
        sql = """
            SELECT kind, name 
            FROM symbols 
            WHERE path = ? AND line <= ? 
            ORDER BY line DESC 
            LIMIT 1
        """
        with self._read_lock:
            row = self._read.execute(sql, (path, line_no)).fetchone()
        
        if row:
            return f"{row['kind']}: {row['name']}"
        return None

    def _is_exact_symbol(self, name: str) -> bool:
        """Check if a symbol with this exact name exists (v2.6.0)."""
        with self._read_lock:
            row = self._read.execute("SELECT 1 FROM symbols WHERE name = ? LIMIT 1", (name,)).fetchone()
        return bool(row)

    def repo_candidates(self, q: str, limit: int = 3, root_ids: Optional[list[str]] = None) -> List[Dict[str, Any]]:
        return self.engine.repo_candidates(q, limit, root_ids=root_ids or [])
