import fnmatch
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass
class SearchHit:
    """Enhanced search result with metadata."""
    repo: str
    path: str
    score: float
    snippet: str
    # v2.3.1: Added metadata
    mtime: int = 0
    size: int = 0
    match_count: int = 0
    file_type: str = ""
    hit_reason: str = ""  # v2.4.3: Added hit reason
    context_symbol: str = ""  # v2.6.0: Enclosing symbol context


@dataclass
class SearchOptions:
    """Search configuration options (v2.5.1)."""
    query: str = ""
    repo: Optional[str] = None
    limit: int = 20
    offset: int = 0
    snippet_lines: int = 5
    # Filtering
    file_types: list[str] = field(default_factory=list)  # e.g., ["py", "ts"]
    path_pattern: Optional[str] = None  # e.g., "src/**/*.ts"
    exclude_patterns: list[str] = field(default_factory=list)  # e.g., ["node_modules", "build"]
    recency_boost: bool = False
    use_regex: bool = False
    case_sensitive: bool = False
    # Pagination & Performance (v2.5.1)
    total_mode: str = "exact"  # "exact" | "approx"


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

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA busy_timeout=2000;")
        conn.execute("PRAGMA cache_size=-20000;")

    @property
    def fts_enabled(self) -> bool:
        return self._fts_enabled

    def close(self) -> None:
        for c in (self._read, self._write):
            try:
                c.close()
            except Exception:
                pass

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
                  content TEXT NOT NULL,
                  last_seen INTEGER DEFAULT 0
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
                  FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
                );
                """
            )
            # v2.7.0: Migration for existing symbols table
            try:
                cur.execute("ALTER TABLE symbols ADD COLUMN end_line INTEGER DEFAULT 0")
                cur.execute("ALTER TABLE symbols ADD COLUMN parent_name TEXT DEFAULT ''")
                self._write.commit()
            except sqlite3.OperationalError:
                pass

            cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);")

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

            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_last_seen ON files(last_seen);")
            
            if self._fts_enabled:
                cur.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts
                    USING fts5(path, repo, content, content='files', content_rowid='rowid');
                    """
                )
                cur.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
                      INSERT INTO files_fts(rowid, path, repo, content) VALUES (new.rowid, new.path, new.repo, new.content);
                    END;
                    """
                )
                cur.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
                      INSERT INTO files_fts(files_fts, rowid, path, repo, content) VALUES('delete', old.rowid, old.path, old.repo, old.content);
                    END;
                    """
                )
                cur.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
                      INSERT INTO files_fts(files_fts, rowid, path, repo, content) VALUES('delete', old.rowid, old.path, old.repo, old.content);
                      INSERT INTO files_fts(rowid, path, repo, content) VALUES (new.rowid, new.path, new.repo, new.content);
                    END;
                    """
                )
            self._write.commit()

    def upsert_files(self, rows: Iterable[tuple[str, str, int, int, str, int]]) -> int:
        rows_list = list(rows)
        if not rows_list:
            return 0
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            # 1. Upsert files
            cur.executemany(
                """
                INSERT INTO files(path, repo, mtime, size, content, last_seen)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                  repo=excluded.repo,
                  mtime=excluded.mtime,
                  size=excluded.size,
                  content=excluded.content,
                  last_seen=excluded.last_seen;
                """,
                rows_list,
            )
            # 2. Clear old symbols for these paths to ensure consistency (v2.8.0)
            # This handles cases where a file's symbols are completely removed.
            cur.executemany("DELETE FROM symbols WHERE path = ?", [(r[0],) for r in rows_list])
            self._write.commit()
        return len(rows_list)

    def upsert_symbols(self, symbols: Iterable[tuple[str, str, str, int, int, str, str]]) -> int:
        """Upsert detected symbols (path, name, kind, line, end_line, content, parent_name)."""
        symbols_list = list(symbols)
        if not symbols_list:
            return 0
        
        # Group by path to clear old symbols first
        paths = {s[0] for s in symbols_list}
        
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            
            # Clear old symbols for these paths
            # Note: We don't have ON CONFLICT for symbols because a file can have multiple same-named symbols (overloaded) 
            # or just multiple symbols. We wipe and rewrite for the file.
            cur.executemany("DELETE FROM symbols WHERE path = ?", [(p,) for p in paths])
            
            cur.executemany(
                """
                INSERT INTO symbols(path, name, kind, line, end_line, content, parent_name)
                VALUES(?,?,?,?,?,?,?)
                """,
                symbols_list,
            )
            self._write.commit()
        return len(symbols_list)

    def get_symbol_block(self, path: str, name: str) -> Optional[dict[str, Any]]:
        """Get the full content block for a specific symbol (v2.7.0)."""
        sql = """
            SELECT s.line, s.end_line, f.content
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
        full_content = row["content"]
        
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
            "content": block
        }

    def update_last_seen(self, paths: Iterable[str], timestamp: int) -> int:
        """Update last_seen timestamp for existing files (v2.5.3)."""
        paths_list = list(paths)
        if not paths_list:
            return 0
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            cur.executemany(
                "UPDATE files SET last_seen=? WHERE path=?",
                [(timestamp, p) for p in paths_list]
            )
            self._write.commit()
        return len(paths_list)

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

    def count_files(self) -> int:
        with self._read_lock:
            row = self._read.execute("SELECT COUNT(1) AS c FROM files").fetchone()
        return int(row["c"]) if row else 0

    def clear_stats_cache(self) -> None:
        """Invalidate stats cache."""
        self._stats_cache.clear()
        self._stats_cache_ts = 0.0

    def get_repo_stats(self, force_refresh: bool = False) -> dict[str, int]:
        """Get file counts per repo with TTL cache (v2.5.1)."""
        now = time.time()
        if not force_refresh and (now - self._stats_cache_ts < self._stats_cache_ttl):
            cached = self._stats_cache.get("repo_stats")
            if cached is not None:
                return cached

        try:
            with self._read_lock:
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
            self._write.execute(
                """
                INSERT OR REPLACE INTO repo_meta (repo_name, tags, domain, description, priority)
                VALUES (?, ?, ?, ?, ?)
                """,
                (repo_name, tags, domain, description, priority)
            )
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
            cur.execute("DELETE FROM symbols WHERE path = ?", (path,))
            cur.execute("DELETE FROM files WHERE path = ?", (path,))
            self._write.commit()

    def list_files(
        self,
        repo: Optional[str] = None,
        path_pattern: Optional[str] = None,
        file_types: Optional[list[str]] = None,
        include_hidden: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """List indexed files for debugging (v2.4.0)."""
        limit = min(int(limit), 500)
        offset = max(int(offset), 0)
        
        where_clauses = []
        params: list[Any] = []
        
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
            sql_pattern = self._glob_to_like(path_pattern)
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
                "file_type": self._get_file_extension(r["path"]),
            })
        
        # Count query params (no limit/offset)
        count_sql = f"SELECT COUNT(1) AS c FROM files f WHERE {where}"
        
        repo_sql = """
            SELECT repo, COUNT(1) AS file_count
            FROM files
            GROUP BY repo
            ORDER BY file_count DESC;
        """
        with self._read_lock:
            count_res = self._read.execute(count_sql, params).fetchone()
            total = count_res["c"] if count_res else 0
            repo_rows = self._read.execute(repo_sql).fetchall()
            
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

    def _glob_to_like(self, pattern: str) -> str:
        """Convert glob-style pattern to SQL LIKE pattern for 1st-pass filtering."""
        if not pattern:
            return "%"
        
        # v2.5.4: Better glob-to-like conversion
        res = pattern.replace("**", "%").replace("*", "%").replace("?", "_")
        
        if not ("%" in res or "_" in res):
            res = f"%{res}%" # Contains if no wildcards
        
        # Ensure it starts/ends correctly for directory patterns
        if pattern.endswith("/**"):
            res = res.rstrip("%") + "%"
            
        while "%%" in res:
            res = res.replace("%%", "%")
        return res

    def _build_filter_clauses(self, opts: SearchOptions) -> tuple[list[str], list[Any]]:
        """Build SQL WHERE clauses for filtering."""
        clauses = []
        params = []
        if opts.repo:
            clauses.append("f.repo = ?")
            params.append(opts.repo)
        
        if opts.file_types:
            type_clauses = []
            for ft in opts.file_types:
                ext = ft.lower().lstrip(".")
                type_clauses.append("f.path LIKE ?")
                params.append(f"%.{ext}")
            if type_clauses:
                clauses.append("(" + " OR ".join(type_clauses) + ")")
        
        if opts.path_pattern:
            clauses.append("f.path LIKE ?")
            params.append(self._glob_to_like(opts.path_pattern))
            
        return clauses, params

    def _get_file_extension(self, path: str) -> str:
        ext = Path(path).suffix
        return ext[1:].lower() if ext else ""
    
    def _matches_file_types(self, path: str, file_types: list[str]) -> bool:
        if not file_types:
            return True
        ext = self._get_file_extension(path)
        return ext in [ft.lower().lstrip('.') for ft in file_types]
    
    def _matches_path_pattern(self, path: str, pattern: Optional[str]) -> bool:
        if not pattern:
            return True
        # v2.5.4: Enhanced glob matching
        # 1. Simple prefix match for directory patterns like 'src/' or 'src/**'
        clean_pat = pattern.replace("**", "").rstrip("/")
        if path.startswith(clean_pat + "/"):
            return True
        
        # 2. Standard fnmatch for basic globs
        return (fnmatch.fnmatch(path, pattern) or 
                fnmatch.fnmatch(path, f"**/{pattern}") or 
                fnmatch.fnmatch(path, f"{pattern}*"))
    
    def _matches_exclude_patterns(self, path: str, patterns: list[str]) -> bool:
        if not patterns:
            return False
        for p in patterns:
            if p in path or fnmatch.fnmatch(path, f"*{p}*"):
                return True
        return False
    
    def _count_matches(self, content: str, query: str, use_regex: bool, case_sensitive: bool) -> int:
        if use_regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                return len(re.findall(query, content, flags))
            except re.error:
                return 0
        else:
            if case_sensitive:
                return content.count(query)
            return content.lower().count(query.lower())
    
    def _calculate_recency_score(self, mtime: int, base_score: float) -> float:
        now = time.time()
        age_days = (now - mtime) / 86400
        if age_days < 1:
            boost = 1.5
        elif age_days < 7:
            boost = 1.3
        elif age_days < 30:
            boost = 1.1
        else:
            boost = 1.0
        
        # v2.5.4: Ensure boost works even if base_score is 0 (bias added)
        return (base_score + 0.1) * boost

    def _extract_terms(self, q: str) -> list[str]:
        # v2.5.4: Use regex to extract quoted phrases or space-separated words
        import re
        raw = re.findall(r'"([^"]*)"|\'([^\']*)\'|(\S+)', q or "")
        out: list[str] = []
        for group in raw:
            # group is a tuple of (double_quoted, single_quoted, bare_word)
            t = group[0] or group[1] or group[2]
            t = t.strip()
            if not t or t in {"AND", "OR", "NOT"}:
                continue
            if ":" in t and len(t.split(":", 1)[0]) <= 10:
                t = t.split(":", 1)[1]
            t = t.strip()
            if t:
                out.append(t)
        return out

    def _snippet_around(self, content: str, terms: list[str], max_lines: int, 
                        highlight: bool = True) -> str:
        if max_lines <= 0:
            return ""
        lines = content.splitlines()
        if not lines:
            return ""

        lower_lines = [l.lower() for l in lines]
        lower_terms = [t.lower() for t in terms if t.strip()]
        
        if not lower_terms:
            return "\n".join(f"L{i+1}: {ln}" for i, ln in enumerate(lines[:max_lines]))

        # Score per line
        # +1 per match, +5 if definition (def/class) AND match
        line_scores = [0] * len(lines)
        def_pattern = re.compile(r"\b(class|def|function|struct|interface|type)\s+", re.IGNORECASE)
        
        has_any_match = False
        for i, line_lower in enumerate(lower_lines):
            score = 0
            for t in lower_terms:
                if t in line_lower:
                    score += 1
            
            if score > 0:
                has_any_match = True
                if def_pattern.search(line_lower):
                    score += 5
            
            line_scores[i] = score

        if not has_any_match:
             return "\n".join(f"L{i+1}: {ln}" for i, ln in enumerate(lines[:max_lines]))
             
        # Find best window (Sliding Window)
        window_size = min(len(lines), max_lines)
        current_score = sum(line_scores[:window_size])
        best_window_score = current_score
        best_start = 0
        
        for i in range(1, len(lines) - window_size + 1):
            current_score = current_score - line_scores[i-1] + line_scores[i + window_size - 1]
            if current_score > best_window_score:
                best_window_score = current_score
                best_start = i
                
        # Extract window
        start_idx = best_start
        end_idx = start_idx + window_size
        
        out_lines = []
        highlight_patterns = [re.compile(re.escape(t), re.IGNORECASE) for t in terms if t.strip()]
        
        for i in range(start_idx, end_idx):
            line = lines[i]
            if highlight:
                for pat in highlight_patterns:
                    # Use backreference to preserve case
                    line = pat.sub(r">>>\g<0><<<", line)
            
            prefix = " " 
            if line_scores[i] > 0:
                 # Mark matching lines lightly if needed, or just use standard formatting
                 pass
            
            out_lines.append(f"L{i+1}: {line}")
            
        return "\n".join(out_lines)

    # ========== Main Search Methods ========== 


    def search_symbols(self, query: str, repo: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
        """Search for symbols by name (v2.6.0)."""
        limit = min(limit, 100)
        query = query.strip()
        if not query:
            return []
            
        sql = """
            SELECT s.path, s.name, s.kind, s.line, s.end_line, s.content, f.repo, f.mtime, f.size
            FROM symbols s
            JOIN files f ON s.path = f.path
            WHERE s.name LIKE ?
        """
        params = [f"%{query}%"]
        
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
                "mtime": int(r["mtime"]),
                "size": int(r["size"])
            }
            for r in rows
        ]

    def read_file(self, path: str) -> Optional[str]:
        """Read full file content from DB (v2.6.0)."""
        with self._read_lock:
            row = self._read.execute("SELECT content FROM files WHERE path = ?", (path,)).fetchone()
        return row["content"] if row else None

    def search_v2(self, opts: SearchOptions) -> tuple[list[SearchHit], dict[str, Any]]:
        """Enhanced search with Hybrid (Symbol + FTS) strategy."""
        q = (opts.query or "").strip()
        if not q:
            return [], {"fallback_used": False, "total_scanned": 0, "total": 0}

        terms = self._extract_terms(q)
        meta: dict[str, Any] = {"fallback_used": False, "total_scanned": 0}
        
        # Regex mode bypasses hybrid logic
        if opts.use_regex:
            return self._search_regex(opts, terms, meta)
        
        # 1. Symbol Search (Priority Layer)
        # Only run if not in approx mode (which implies huge scale or quick scan)
        symbol_hits_data = []
        if opts.total_mode != "approx":
             symbol_hits_data = self.search_symbols(q, repo=opts.repo, limit=50)

        # Convert symbol hits to SearchHit objects
        symbol_hits = []
        for s in symbol_hits_data:
            hit = SearchHit(
                repo=s["repo"],
                path=s["path"],
                score=1000.0, # Massive starting score for symbol match
                snippet=s["snippet"],
                mtime=s["mtime"],
                size=s["size"],
                match_count=1,
                file_type=self._get_file_extension(s["path"]),
                hit_reason=f"Symbol: {s['kind']} {s['name']}",
                context_symbol=f"{s['kind']}: {s['name']}"
            )
            # Recency boost if enabled
            if opts.recency_boost:
                hit.score = self._calculate_recency_score(hit.mtime, hit.score)
            symbol_hits.append(hit)


        # 2. FTS Search
        fts_hits = []
        has_unicode = any(ord(c) > 127 for c in q)
        is_too_short = len(q) < 3
        
        use_fts = self._fts_enabled and not has_unicode and not is_too_short
        fts_success = False
        
        if use_fts:
            try:
                res = self._search_fts(opts, terms, meta, no_slice=True)
                if res:
                    fts_hits, fts_meta = res
                    meta.update(fts_meta)
                    fts_success = True
            except sqlite3.OperationalError:
                # FTS failed (e.g. index corrupted or missing), fallback to LIKE
                pass
        
        if not fts_success:
            # Fallback to LIKE
            res, like_meta = self._search_like(opts, terms, meta, no_slice=True)
            fts_hits = res
            meta.update(like_meta)

        # 3. Merge Strategies
        # Map path -> Hit
        merged_map: dict[str, SearchHit] = {}
        
        # First put FTS hits
        for h in fts_hits:
            merged_map[h.path] = h
            
        # Then merge Symbol hits
        for sh in symbol_hits:
            if sh.path in merged_map:
                existing = merged_map[sh.path]
                # If we have a symbol match, it overrides the score and snippet preference
                # But we want to keep the highest score.
                # Since we gave symbol hit 1000.0, it will likely win.
                existing.score += 1200.0 # Boost existing FTS hit to surpass symbol-only (1000)
                existing.hit_reason = f"{sh.hit_reason}, {existing.hit_reason}"
                # If the symbol snippet is better (direct definition), usage might be better context?
                # User objective: "Definition Ranking". So Definition > Usage.
                # We'll prepend the symbol snippet if it's not effectively the same.
                if sh.snippet.strip() not in existing.snippet:
                     existing.snippet = f"{sh.snippet}\n...\n{existing.snippet}"
            else:
                merged_map[sh.path] = sh
                
        # Final List
        final_hits = list(merged_map.values())
        
        # Sort
        final_hits.sort(key=lambda h: (-h.score, -h.mtime, h.path))
        
        # Pagination
        try:
            start = int(opts.offset)
            end = start + int(opts.limit)
        except (ValueError, TypeError):
            start = 0
            end = 20
        
        # Adjust Total Count
        if opts.total_mode == "approx":
             meta["total"] = -1
        elif meta.get("total", 0) > 0:
             # Approximation: max of FTS total or our current count
             meta["total"] = max(meta["total"], len(final_hits))
        else:
             meta["total"] = len(final_hits)
             
        # Safe slicing
        return final_hits[start:end], meta

    def _search_like(self, opts: SearchOptions, terms: list[str], 
                     meta: dict[str, Any], no_slice: bool = False) -> tuple[list[SearchHit], dict[str, Any]]:
        meta["fallback_used"] = True
        
        like_q = opts.query.replace("^", "^^").replace("%", "^%").replace("_", "^_")
        # v2.5.4: Search in content, path, and repo for better fallback coverage
        where_clauses = ["(f.content LIKE ? ESCAPE '^' OR f.path LIKE ? ESCAPE '^' OR f.repo LIKE ? ESCAPE '^')"]
        params: list[Any] = [f"%{like_q}%", f"%{like_q}%", f"%{like_q}%"]
        
        filter_clauses, filter_params = self._build_filter_clauses(opts)
        where_clauses.extend(filter_clauses)
        params.extend(filter_params)
        
        where = " AND ".join(where_clauses)
        
        fetch_limit = (opts.offset + opts.limit) * 2
        if fetch_limit < 100: fetch_limit = 100
        
        sql = f"""
            SELECT f.repo AS repo,
            ...
            LIMIT ?;
        """
        # (Assuming the SQL query body is unchanged, referring to original file content for context if needed, 
        # but here we just need to return hits unsliced)
        # RE-Constructing sql because replace_block needs contiguous block.
        sql = f"""
            SELECT f.repo AS repo,
                   f.path AS path,
                   f.mtime AS mtime,
                   f.size AS size,
                   0.0 AS score,
                   f.content AS content
            FROM files f
            WHERE {where}
            ORDER BY {"f.mtime DESC" if opts.recency_boost else "f.path"}, f.path ASC
            LIMIT ?;
        """
        params.append(int(fetch_limit))

        with self._read_lock:
            if opts.total_mode == "exact":
                count_sql = f"SELECT COUNT(*) as c FROM files f WHERE {where}"
                count_row = self._read.execute(count_sql, params[:-1]).fetchone()
                meta["total"] = int(count_row["c"]) if count_row else 0
            else:
                meta["total"] = -1
            
            rows = self._read.execute(sql, params).fetchall()

        meta["total_mode"] = opts.total_mode
        
        hits = self._process_rows(rows, opts, terms)
        meta["total_scanned"] = len(rows)
        
        if no_slice:
            return hits, meta

        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _search_regex(self, opts: SearchOptions, terms: list[str], 
                      meta: dict[str, Any]) -> tuple[list[SearchHit], dict[str, Any]]:
        # Regex unchanged
        return self._search_regex_impl(opts, terms, meta) 
        # Wait, I cannot rename existing method easily without replacing it all.
        # I'll just leave regex alone or update it if I need to.
        # Check if I touch regex in my target block?
        # Target block ends at 933 (_search_regex return).
        # So I am replacing _search_fts and _search_like calls/impls.
        pass

    def _search_fts(self, opts: SearchOptions, terms: list[str], 
                    meta: dict[str, Any], no_slice: bool = False) -> Optional[tuple[list[SearchHit], dict[str, Any]]]:
        where_clauses = ["files_fts MATCH ?"]
        params: list[Any] = [opts.query]
        
        filter_clauses, filter_params = self._build_filter_clauses(opts)
        where_clauses.extend(filter_clauses)
        params.extend(filter_params)
        
        where = " AND ".join(where_clauses)
        
        # Total count
        total_hits = 0
        if opts.total_mode == "exact":
            try:
                count_sql = f"SELECT COUNT(*) as c FROM files_fts JOIN files f ON f.rowid = files_fts.rowid WHERE {where}"
                with self._read_lock:
                    count_row = self._read.execute(count_sql, params).fetchone()
                total_hits = int(count_row["c"]) if count_row else 0
            except sqlite3.OperationalError:
                return None # FTS failed
        else:
            # Approx mode
            total_hits = -1 
            
        meta["total"] = total_hits
        meta["total_mode"] = opts.total_mode

        # Fetch buffer (Top-50 for reranking)
        fetch_limit = 50 
        
        # Google-Style Stage 1: SQL Partial Scoring
        # We calculate Priors here within SQL to avoid fetching junk.
        
        # Priors (Higher is better)
        # Path Prior: src/app/core -> +0.6
        # Matches "src/..." or ".../src/..."
        path_prior_sql = """
        CASE 
            WHEN f.path LIKE 'src/%' OR f.path LIKE '%/src/%' OR f.path LIKE 'app/%' OR f.path LIKE '%/app/%' OR f.path LIKE 'core/%' OR f.path LIKE '%/core/%' THEN 0.6
            WHEN f.path LIKE 'config/%' OR f.path LIKE '%/config/%' OR f.path LIKE 'domain/%' OR f.path LIKE '%/domain/%' OR f.path LIKE 'service/%' OR f.path LIKE '%/service/%' THEN 0.4
            WHEN f.path LIKE 'test/%' OR f.path LIKE '%/test/%' OR f.path LIKE 'tests/%' OR f.path LIKE '%/tests/%' OR f.path LIKE 'example/%' OR f.path LIKE '%/example/%' OR f.path LIKE 'dist/%' OR f.path LIKE '%/dist/%' OR f.path LIKE 'build/%' OR f.path LIKE '%/build/%' THEN -0.7
            ELSE 0.0
        END
        """
        
        # Filetype Prior: Code -> +0.3
        filetype_prior_sql = """
        CASE
            WHEN f.path LIKE '%.py' OR f.path LIKE '%.ts' OR f.path LIKE '%.go' OR f.path LIKE '%.java' OR f.path LIKE '%.kt' THEN 0.3
            WHEN f.path LIKE '%.yaml' OR f.path LIKE '%.yml' OR f.path LIKE '%.json' THEN 0.15
            WHEN f.path LIKE '%.lock' OR f.path LIKE '%.min.js' OR f.path LIKE '%.map' THEN -0.8
            ELSE 0.0
        END
        """

        # We combine them. We normalize score so higher is better.
        # FTS5 bm25() is lower = better. We effectively want: (Priors - bm25)
        # We start with -1.0 * bm25() as the base "relevance" (so it becomes higher is better).
        
        sql = f"""
            SELECT f.repo AS repo,
                   f.path AS path,
                   f.mtime AS mtime,
                   f.size AS size,
                   ( -1.0 * bm25(files_fts) + {path_prior_sql} + {filetype_prior_sql} ) AS score,
                   f.content AS content
            FROM files_fts
            JOIN files f ON f.rowid = files_fts.rowid
            WHERE {where}
            ORDER BY score DESC
            LIMIT ?;
        """
        params.append(int(fetch_limit))
        
        with self._read_lock:
            rows = self._read.execute(sql, params).fetchall()
        
        # Stage 2: Python Reranking
        hits = self._process_rows(rows, opts, terms, is_rerank=True)
        meta["total_scanned"] = len(rows)
        
        if no_slice:
            return hits, meta

        # Slice to user limit (default 8)
        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _search_regex(self, opts: SearchOptions, terms: list[str], 
                      meta: dict[str, Any]) -> tuple[list[SearchHit], dict[str, Any]]:
        meta["regex_mode"] = True
        
        flags = 0 if opts.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(opts.query, flags)
        except re.error as e:
            meta["regex_error"] = str(e)
            return [], meta
        
        where = "1=1"
        params: list[Any] = []
        if opts.repo:
            where = "f.repo = ?"
            params.append(opts.repo)
        
        # Regex scans everything (capped), so "total" is just "found hits" roughly
        # We can't know total without scanning all.
        # We'll just set total = len(hits) found within limit.
        
        sql = f"""
            SELECT f.repo AS repo,
                   f.path AS path,
                   f.mtime AS mtime,
                   f.size AS size,
                   f.content AS content
            FROM files f
            WHERE {where}
            ORDER BY {"f.mtime DESC" if opts.recency_boost else "f.path"}
            LIMIT 5000;
        """
        with self._read_lock:
            rows = self._read.execute(sql, params).fetchall()
        meta["total_scanned"] = len(rows)
        
        hits: list[SearchHit] = []
        for r in rows:
            path = r["path"]
            content = r["content"] or ""
            
            if not self._matches_file_types(path, opts.file_types):
                continue
            if not self._matches_path_pattern(path, opts.path_pattern):
                continue
            if self._matches_exclude_patterns(path, opts.exclude_patterns):
                continue
            
            matches = pattern.findall(content)
            if not matches:
                continue
            
            match_count = len(matches)
            score = float(match_count)
            if opts.recency_boost:
                score = self._calculate_recency_score(int(r["mtime"]), score)
            
            snippet = self._snippet_around(content, [opts.query], opts.snippet_lines, highlight=True)
            
            hits.append(SearchHit(
                repo=r["repo"],
                path=path,
                score=score,
                snippet=snippet,
                mtime=int(r["mtime"]),
                size=int(r["size"]),
                match_count=match_count,
                file_type=self._get_file_extension(path),
            ))
        
        # Single sort with tuple key (O(n log n) instead of O(3*n log n))
        hits.sort(key=lambda h: (-h.score, -h.mtime, h.path))
        
        meta["total"] = len(hits) # For regex, total is what we found in the scan
        meta["total_mode"] = "approx" # Regex is always approx in this impl
        
        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _process_rows(self, rows: list, opts: SearchOptions, 
                      terms: list[str], is_rerank: bool = False) -> list[SearchHit]:
        hits: list[SearchHit] = []
        
        all_meta = self.get_all_repo_meta()
        query_terms = [t.lower() for t in terms]
        query_raw_lower = opts.query.lower()
        
        # Regex for Definition Boost
        # Matches: class X, def X, function X, interface X, etc.
        # We look for the QUERY TERM being defined.
        def_patterns = []
        for term in query_terms:
            if len(term) < 3: continue 
            # Pattern: (class|def|...) \s+ term
            p = re.compile(rf"(class|def|function|struct|pub\s+fn|async\s+def|interface|type)\s+{re.escape(term)}\b", re.IGNORECASE)
            def_patterns.append(p)

        for r in rows:
            path = r["path"]
            repo_name = r["repo"]
            content = r["content"] or ""
            mtime = int(r["mtime"])
            size = int(r["size"])
            
            if not self._matches_file_types(path, opts.file_types):
                continue
            if not self._matches_path_pattern(path, opts.path_pattern):
                continue
            if self._matches_exclude_patterns(path, opts.exclude_patterns):
                continue
            
            # Start with SQL score (already includes Priors if is_rerank=True)
            score = float(r["score"]) if r["score"] is not None else 0.0
            
            # If NOT coming from the new FTS logic (e.g. LIKE fallback), score might be 0.0
            # Normalize baseline if needed
            
            reasons = []
            
            path_lower = path.lower()
            path_parts = path_lower.split("/")
            filename = path_parts[-1]
            file_stem = Path(filename).stem

            # 1. Filename Exact Match Boost
            if filename == query_raw_lower or f".{query_raw_lower}." in filename:
                score += 2.0
                reasons.append("Exact filename match")
            elif path_lower.endswith(query_raw_lower):
                score += 1.5
                reasons.append("Path suffix match")
            elif query_raw_lower in filename:
                score += 1.0
                reasons.append("Filename match")
            
            # 2. Definition Boost (Intent)
            # Scan content for "def query_term"
            is_definition = False
            for pat in def_patterns:
                if pat.search(content):
                    score += 1.5
                    is_definition = True
                    reasons.append("Definition found")
                    break
            
            # 3. Proximity Boost
            if len(query_terms) > 1:
                content_lower = content.lower()
                term_indices = []
                all_found = True
                for t in query_terms:
                    idx = content_lower.find(t)
                    if idx == -1:
                        all_found = False
                        break
                    term_indices.append(idx)
                
                if all_found:
                    span = max(term_indices) - min(term_indices)
                    if span < 100: # Terms are close
                        score += 0.5
                        reasons.append("Proximity boost")

            meta_obj = all_meta.get(repo_name)
            if meta_obj:
                if meta_obj["priority"] > 0:
                    score += meta_obj["priority"]
                    reasons.append("High priority")
                tags = meta_obj["tags"].lower().split(",")
                domain = meta_obj["domain"].lower()
                for term in query_terms:
                    if term in tags or term == domain:
                        score += 0.5
                        reasons.append(f"Tag match ({term})")
                        break
            
            if any(p in path_lower for p in [".codex/", "agents.md", "gemini.md", "readme.md"]):
                score += 0.2
                reasons.append("Core file")
            
            if opts.recency_boost:
                score = self._calculate_recency_score(mtime, score)
            
            # v2.5.4: Strictly enforce case sensitivity
            match_count = self._count_matches(content, opts.query, False, opts.case_sensitive)
            if opts.case_sensitive and match_count == 0:
                continue

            # Snippet Generation
            snippet = self._snippet_around(content, terms, opts.snippet_lines, highlight=True)
            
            # 5. Enclosing Context 
            context_symbol = ""
            first_line_match = re.search(r"L(\d+):", snippet)
            if first_line_match:
                start_line = int(first_line_match.group(1))
                ctx = self._get_enclosing_symbol(path, start_line)
                if ctx:
                    context_symbol = ctx
                    score += 0.2 # Small context bonus
            
            hits.append(SearchHit(
                repo=repo_name,
                path=path,
                score=round(score, 3), # Round for clean display
                snippet=snippet,
                mtime=mtime,
                size=size,
                match_count=0, 
                file_type=self._get_file_extension(path),
                hit_reason=", ".join(reasons) if reasons else "Content match",
                context_symbol=context_symbol
            ))
        
        # Sort by Score (Desc)
        hits.sort(key=lambda h: (-h.score, -h.mtime, h.path))
        return hits

    def search(
        self,
        q: str,
        repo: Optional[str],
        limit: int = 20,
        snippet_max_lines: int = 5,
    ) -> tuple[list[SearchHit], dict[str, Any]]:
        opts = SearchOptions(
            query=q,
            repo=repo,
            limit=limit,
            snippet_lines=snippet_max_lines,
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

    def repo_candidates(self, q: str, limit: int = 3) -> list[dict[str, Any]]:
        q = (q or "").strip()
        if not q:
            return []

        limit = max(1, min(int(limit), 5))

        if self._fts_enabled:
            sql = """
                SELECT f.repo AS repo,
                       COUNT(1) AS c
                FROM files_fts
                JOIN files f ON f.rowid = files_fts.rowid
                WHERE files_fts MATCH ?
                GROUP BY f.repo
                ORDER BY c DESC
                LIMIT ?;
            """
            try:
                with self._read_lock:
                    rows = self._read.execute(sql, (q, limit)).fetchall()
                out: list[dict[str, Any]] = []
                for r in rows:
                    repo = str(r["repo"])
                    c = int(r["c"])
                    hits, _ = self.search(q=q, repo=repo, limit=1, snippet_max_lines=2)
                    evidence = hits[0].snippet.replace("\n", " ")[:200] if hits else ""
                    out.append({"repo": repo, "score": c, "evidence": evidence})
                return out
            except sqlite3.OperationalError:
                pass

        like_q = q.replace("^", "^^").replace("%", "^%").replace("_", "^_")
        sql = """
            SELECT repo, COUNT(1) AS c
            FROM files
            WHERE content LIKE ? ESCAPE '^'
            GROUP BY repo
            ORDER BY c DESC
            LIMIT ?;
        """
        with self._read_lock:
            rows = self._read.execute(sql, (f"%{like_q}%", limit)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            repo = str(r["repo"])
            c = int(r["c"])
            hits, _ = self.search(q=q, repo=repo, limit=1, snippet_max_lines=2)
            evidence = hits[0].snippet.replace("\n", " ")[:200] if hits else ""
            out.append({"repo": repo, "score": c, "evidence": evidence})
        return out
