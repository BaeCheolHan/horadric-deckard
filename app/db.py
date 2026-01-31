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
                  content TEXT NOT NULL
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

            # Index for efficient filtering
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_repo ON files(repo);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime DESC);")
            
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

    def upsert_files(self, rows: Iterable[tuple[str, str, int, int, str]]) -> int:
        rows_list = list(rows)
        if not rows_list:
            return 0
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            cur.executemany(
                """
                INSERT INTO files(path, repo, mtime, size, content)
                VALUES(?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                  repo=excluded.repo,
                  mtime=excluded.mtime,
                  size=excluded.size,
                  content=excluded.content;
                """,
                rows_list,
            )
            self._write.commit()
        return len(rows_list)

    def delete_files(self, paths: Iterable[str]) -> int:
        paths_list = list(paths)
        if not paths_list:
            return 0
        with self._lock:
            cur = self._write.cursor()
            cur.execute("BEGIN")
            cur.executemany("DELETE FROM files WHERE path=?", [(p,) for p in paths_list])
            self._write.commit()
        return len(paths_list)

    def get_file_meta(self, path: str) -> Optional[tuple[int, int]]:
        row = self._read.execute("SELECT mtime, size FROM files WHERE path=?", (path,)).fetchone()
        if not row:
            return None
        return int(row["mtime"]), int(row["size"])

    def get_index_status(self) -> dict[str, Any]:
        """Get index metadata for debugging/UI (v2.4.2)."""
        row = self._read.execute("SELECT COUNT(1) AS c, MAX(mtime) AS last_mtime FROM files").fetchone()
        count = int(row["c"]) if row and row["c"] else 0
        last_mtime = int(row["last_mtime"]) if row and row["last_mtime"] else 0
        
        return {
            "total_files": count,
            "last_scan_time": last_mtime,
            "db_size_bytes": Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0
        }

    def count_files(self) -> int:
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
        row = self._read.execute("SELECT * FROM repo_meta WHERE repo_name = ?", (repo_name,)).fetchone()
        return dict(row) if row else None

    def get_all_repo_meta(self) -> dict[str, dict[str, Any]]:
        """Get all repo metadata as a map."""
        rows = self._read.execute("SELECT * FROM repo_meta").fetchall()
        return {row["repo_name"]: dict(row) for row in rows}

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
        
        if repo:
            where_clauses.append("f.repo = ?")
            params.append(repo)
        
        if not include_hidden:
            where_clauses.append("f.path NOT LIKE '%/.%'")
            where_clauses.append("f.path NOT LIKE '.%'")
        
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
        params.extend([limit, offset])
        
        rows = self._read.execute(sql, params).fetchall()
        
        files: list[dict[str, Any]] = []
        for r in rows:
            path = r["path"]
            if file_types and not self._matches_file_types(path, file_types):
                continue
            if path_pattern and not self._matches_path_pattern(path, path_pattern):
                continue
            
            files.append({
                "repo": r["repo"],
                "path": path,
                "mtime": int(r["mtime"]),
                "size": int(r["size"]),
                "file_type": self._get_file_extension(path),
            })
        
        count_sql = f"SELECT COUNT(1) AS c FROM files f WHERE {where}"
        count_params = params[:-2]
        total = self._read.execute(count_sql, count_params).fetchone()["c"]
        
        repo_sql = """
            SELECT repo, COUNT(1) AS file_count
            FROM files
            GROUP BY repo
            ORDER BY file_count DESC;
        """
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
        res = pattern.replace("**", "%").replace("*", "%").replace("?", "_")
        # Ensure it matches anywhere if not anchored
        if not (res.startswith("/") or res.startswith("%")):
            res = "%" + res
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
        return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"**/{pattern}")
    
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
        return base_score * boost

    def _extract_terms(self, q: str) -> list[str]:
        raw = [t.strip().strip('"\'') for t in (q or "").split()]
        out: list[str] = []
        for t in raw:
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

        lower = content.lower()
        pos = -1
        matched_term = ""
        for t in terms:
            p = lower.find(t.lower())
            if p != -1:
                pos = p
                matched_term = t
                break

        if pos == -1:
            slice_lines = lines[:max_lines]
            return "\n".join(f"L{i+1}: {ln}" for i, ln in enumerate(slice_lines))

        line_idx = lower[:pos].count("\n")
        half = max_lines // 2
        start = max(0, line_idx - half)
        end = min(len(lines), start + max_lines)
        start = max(0, end - max_lines)

        out_lines = []
        for i in range(start, end):
            line = lines[i]
            if highlight and matched_term:
                pattern = re.compile(re.escape(matched_term), re.IGNORECASE)
                line = pattern.sub(f">>>{matched_term}<<<", line)
            prefix = "→" if i == line_idx else " "
            out_lines.append(f"{prefix}L{i+1}: {line}")
        return "\n".join(out_lines)

    # ========== Main Search Methods ========== 

    def search_v2(self, opts: SearchOptions) -> tuple[list[SearchHit], dict[str, Any]]:
        """Enhanced search with all options (v2.3.1)."""
        q = (opts.query or "").strip()
        if not q:
            return [], {"fallback_used": False, "total_scanned": 0, "total": 0}

        terms = self._extract_terms(q)
        meta: dict[str, Any] = {"fallback_used": False, "total_scanned": 0}
        
        # Regex mode
        if opts.use_regex:
            return self._search_regex(opts, terms, meta)
        
        # FTS mode (default)
        if self._fts_enabled:
            result = self._search_fts(opts, terms, meta)
            if result is not None:
                return result
        
        # LIKE fallback
        return self._search_like(opts, terms, meta)

    def _search_fts(self, opts: SearchOptions, terms: list[str], 
                    meta: dict[str, Any]) -> Optional[tuple[list[SearchHit], dict[str, Any]]]:
        where_clauses = ["files_fts MATCH ?"]
        params: list[Any] = [opts.query]
        
        filter_clauses, filter_params = self._build_filter_clauses(opts)
        where_clauses.extend(filter_clauses)
        params.extend(filter_params)
        
        where = " AND ".join(where_clauses)
        
        # Total count
        try:
            count_sql = f"SELECT COUNT(*) as c FROM files_fts JOIN files f ON f.rowid = files_fts.rowid WHERE {where}"
            count_row = self._read.execute(count_sql, params).fetchone()
            total_hits = int(count_row["c"]) if count_row else 0
        except sqlite3.OperationalError:
            return None # FTS failed
            
        meta["total"] = total_hits
        meta["total_mode"] = opts.total_mode

        # Fetch buffer to allow for Python-side re-ranking and further filtering (excludes)
        fetch_limit = (opts.offset + opts.limit) * 2
        if fetch_limit < 100: fetch_limit = 100
        
        sql = f"""
            SELECT f.repo AS repo,
                   f.path AS path,
                   f.mtime AS mtime,
                   f.size AS size,
                   bm25(files_fts) AS score,
                   f.content AS content
            FROM files_fts
            JOIN files f ON f.rowid = files_fts.rowid
            WHERE {where}
            ORDER BY {"f.mtime DESC, score" if opts.recency_boost else "score"}, f.path ASC
            LIMIT ?;
        """
        params.append(int(fetch_limit))
        
        rows = self._read.execute(sql, params).fetchall()
        
        hits = self._process_rows(rows, opts, terms)
        meta["total_scanned"] = len(rows)
        
        # Slice for pagination
        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _search_like(self, opts: SearchOptions, terms: list[str], 
                     meta: dict[str, Any]) -> tuple[list[SearchHit], dict[str, Any]]:
        meta["fallback_used"] = True
        
        like_q = opts.query.replace("^", "^^").replace("%", "^%").replace("_", "^_")
        where_clauses = ["f.content LIKE ? ESCAPE '^'"]
        params: list[Any] = [f"%{like_q}%"]
        
        filter_clauses, filter_params = self._build_filter_clauses(opts)
        where_clauses.extend(filter_clauses)
        params.extend(filter_params)
        
        where = " AND ".join(where_clauses)
        
        # Total count
        count_sql = f"SELECT COUNT(*) as c FROM files f WHERE {where}"
        count_row = self._read.execute(count_sql, params).fetchone()
        meta["total"] = int(count_row["c"]) if count_row else 0
        meta["total_mode"] = opts.total_mode

        fetch_limit = (opts.offset + opts.limit) * 2
        if fetch_limit < 100: fetch_limit = 100
        
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
        rows = self._read.execute(sql, params).fetchall()
        
        hits = self._process_rows(rows, opts, terms)
        meta["total_scanned"] = len(rows)
        
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
        
        # Sort by score (stable: score DESC, mtime DESC, path ASC)
        hits.sort(key=lambda h: h.path)
        hits.sort(key=lambda h: h.mtime, reverse=True)
        hits.sort(key=lambda h: h.score, reverse=True)
        
        meta["total"] = len(hits) # For regex, total is what we found in the scan
        meta["total_mode"] = "approx" # Regex is always approx in this impl
        
        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _process_rows(self, rows: list, opts: SearchOptions, 
                      terms: list[str]) -> list[SearchHit]:
        hits: list[SearchHit] = []
        
        all_meta = self.get_all_repo_meta()
        query_terms = [t.lower() for t in terms]
        query_raw_lower = opts.query.lower()
        symbol_pattern = re.compile(r"^\s*(class|def|function|struct|pub\s+fn|async\s+def|interface|type)\s+", re.MULTILINE)

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
            
            base_score = float(r["score"]) if r["score"] is not None else 0.0
            score = -base_score if base_score < 0 else base_score
            reasons = []
            
            path_lower = path.lower()
            path_parts = path_lower.split("/")
            filename = path_parts[-1]
            file_stem = Path(filename).stem

            if file_stem == query_raw_lower:
                score += 50.0
                reasons.append("Exact filename match")
            elif path_lower.endswith(query_raw_lower):
                score += 40.0
                reasons.append("Path suffix match")
            
            if query_raw_lower in filename:
                score += 20.0
                reasons.append("Filename match")
            
            for part in path_parts[:-1]:
                if part == query_raw_lower:
                    score += 15.0
                    reasons.append(f"Dir match ({part})")
                    break
            
            meta_obj = all_meta.get(repo_name)
            if meta_obj:
                if meta_obj["priority"] > 0:
                    score += meta_obj["priority"]
                    reasons.append("High priority")
                tags = meta_obj["tags"].lower().split(",")
                domain = meta_obj["domain"].lower()
                for term in query_terms:
                    if term in tags or term == domain:
                        score += 5.0
                        reasons.append(f"Tag match ({term})")
                        break
            
            if any(p in path_lower for p in [".codex/", "agents.md", "gemini.md", "readme.md"]):
                score += 2.0
                reasons.append("Core file")
            
            if opts.recency_boost:
                score = self._calculate_recency_score(mtime, score)
            
            match_count = self._count_matches(content, opts.query, False, opts.case_sensitive)
            snippet = self._snippet_around(content, terms, opts.snippet_lines, highlight=True)
            
            if symbol_pattern.search(snippet):
                score += 10.0
                reasons.append("Symbol definition")

            hits.append(SearchHit(
                repo=repo_name,
                path=path,
                score=round(score, 3),
                snippet=snippet,
                mtime=mtime,
                size=size,
                match_count=match_count,
                file_type=self._get_file_extension(path),
                hit_reason=", ".join(reasons) if reasons else "Content match"
            ))
        
        # Sort by score (stable: score DESC, mtime DESC, path ASC)
        hits.sort(key=lambda h: h.path)
        hits.sort(key=lambda h: h.mtime, reverse=True)
        hits.sort(key=lambda h: h.score, reverse=True)
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
        rows = self._read.execute(sql, (f"%{like_q}%", limit)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            repo = str(r["repo"])
            c = int(r["c"])
            hits, _ = self.search(q=q, repo=repo, limit=1, snippet_max_lines=2)
            evidence = hits[0].snippet.replace("\n", " ")[:200] if hits else ""
            out.append({"repo": repo, "score": c, "evidence": evidence})
        return out