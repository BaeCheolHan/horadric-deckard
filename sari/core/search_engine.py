import sqlite3
import re
import time
from typing import List, Tuple, Optional, Any, Dict
from .models import SearchHit, SearchOptions
from .ranking import snippet_around, get_file_extension
from .scoring import ScoringPolicy
from .engine.tantivy_engine import TantivyEngine

from .db.storage import GlobalStorageManager

class SearchEngine:
    def __init__(self, db, scoring_policy: ScoringPolicy = None, tantivy_engine: Optional[TantivyEngine] = None):
        self.db = db
        self.scoring_policy = scoring_policy or ScoringPolicy()
        self.tantivy_engine = tantivy_engine
        self._snippet_cache: Dict[tuple, str] = {}
        self._snippet_lru: List[tuple] = []
        self.storage = GlobalStorageManager.get_instance(db)

    def search_v2(self, opts: SearchOptions) -> Tuple[List[SearchHit], Dict[str, Any]]:
        """Enhanced search with Score Normalization and Merged Results."""
        if hasattr(self.db, "coordinator") and self.db.coordinator:
            self.db.coordinator.notify_search_start()

        q = (opts.query or "").strip()
        if not q: return [], {"total": 0}

        root_id = list(opts.root_ids)[0] if opts.root_ids else None
        meta: Dict[str, Any] = {"engine": "hybrid"}

        # 1. L2 Cache (Recent) - 최상위 우선순위
        recent_rows = self.storage.get_recent_files(q, root_id=root_id, limit=opts.limit)
        recent_hits = self._process_sqlite_rows(recent_rows, opts)
        for h in recent_hits:
            h.hit_reason = "L2 Cache (Recent)"
            h.score = 100.0 # 매우 높은 고정 점수
        
        seen_paths = {h.path for h in recent_hits}
        all_hits = recent_hits

        # 2. Tantivy (Primary DB Search)
        if self.tantivy_engine and not opts.use_regex:
            hits = self.tantivy_engine.search(q, root_id=root_id, limit=opts.limit)
            if hits:
                t_hits = self._process_tantivy_hits(hits, opts)
                # Tantivy 점수 정규화: 최고점을 10.0으로 맞춤 (DB 검색 중 최상위)
                max_t = max((h.score for h in t_hits), default=1.0)
                for h in t_hits:
                    h.score = (h.score / max_t) * 10.0
                    if h.path not in seen_paths:
                        all_hits.append(h)
                        seen_paths.add(h.path)

        # 3. SQLite (Fallback/Secondary DB Search)
        if len(all_hits) < opts.limit:
            cur = self.db._get_conn().cursor()
            if getattr(self.db, "settings", None) and self.db.settings.ENABLE_FTS:
                fts_q = self._fts_query(q)
                sql = ("SELECT f.path, f.rel_path, f.root_id, f.repo, f.mtime, f.size, f.content "
                       "FROM files_fts JOIN files f ON files_fts.rowid = f.rowid "
                       "WHERE files_fts MATCH ?")
                params = [fts_q]
                if root_id: sql += " AND f.root_id = ?"; params.append(root_id)
                
                cur.execute(sql + f" LIMIT {opts.limit}", params)
                db_hits = self._process_sqlite_rows(cur.fetchall(), opts)
                for h in db_hits:
                    h.score = 5.0 # SQLite FTS는 Tantivy보다 낮은 가중치
                    if h.path not in seen_paths:
                        all_hits.append(h)
                        seen_paths.add(h.path)
            else:
                like_q = f"%{q}%"
                sql = (
                    "SELECT path, root_id, repo, mtime, size, content FROM files "
                    "WHERE (path LIKE ? OR rel_path LIKE ? OR content LIKE ?)"
                )
                params = [like_q, like_q, like_q]
                if root_id:
                    sql += " AND root_id = ?"
                    params.append(root_id)
                cur.execute(sql + f" LIMIT {opts.limit}", params)
                db_hits = self._process_sqlite_rows(cur.fetchall(), opts)
                for h in db_hits:
                    h.score = 4.0
                    if h.path not in seen_paths:
                        all_hits.append(h)
                        seen_paths.add(h.path)

        # 최종 정렬: 점수 내림차순 -> 시간 내림차순
        all_hits.sort(key=lambda x: (-x.score, -x.mtime))
        return all_hits[:opts.limit], meta

    def _process_sqlite_rows(self, rows: list, opts: SearchOptions) -> List[SearchHit]:
        hits: List[SearchHit] = []
        for r in rows:
            # Legacy/normalized row: (path, root_id, repo, mtime, size, content)
            # FTS row: (path, rel_path, root_id, repo, mtime, size, content)
            if len(r) >= 7:
                path = r[0]
                repo = r[3]
                mtime = r[4]
                size = r[5]
                content = r[6]
            elif len(r) >= 6:
                path = r[0]
                repo = r[2]
                mtime = r[3]
                size = r[4]
                content = r[5]
            else:
                continue
            hits.append(SearchHit(
                repo=repo,
                path=path,
                score=1.0,
                snippet=self._snippet_for(path, opts.query, content),
                mtime=mtime,
                size=size,
                match_count=1,
                file_type=get_file_extension(path),
                hit_reason="SQLite Fallback",
            ))
        return hits

    def _process_tantivy_hits(self, hits: list, opts: SearchOptions) -> List[SearchHit]:
        results: List[SearchHit] = []
        for h in hits:
            path = h.get("path", "")
            snippet = f"Match in {path}"
            try:
                content = self.db.read_file(path)
                if content:
                    snippet = self._snippet_for(path, opts.query, content)
            except Exception:
                pass
            results.append(SearchHit(
                repo=h.get("repo", ""),
                path=path,
                score=h.get("score", 0.0),
                snippet=snippet,
                mtime=h.get("mtime", 0),
                size=h.get("size", 0),
                match_count=1,
                file_type=get_file_extension(path),
                hit_reason="Tantivy Search",
            ))
        return results

    def _fts_query(self, q: str) -> str:
        raw = (q or "").strip()
        if not raw:
            return raw
        # Normalize common OR separators
        raw = raw.replace("||", " OR ").replace("|", " OR ")
        tokens = re.findall(r'\(|\)|"[^"]+"|\bAND\b|\bOR\b|\bNOT\b|\bNEAR/\d+\b|\bNEAR\b|[0-9A-Za-z_\u00A1-\uFFFF]+', raw, flags=re.IGNORECASE)
        if not tokens:
            return raw.replace('"', " ")
        out = []
        for t in tokens:
            upper = t.upper()
            if upper in {"AND", "OR", "NOT"} or upper.startswith("NEAR"):
                out.append(upper)
                continue
            if t in {"(", ")"}:
                out.append(t)
                continue
            if t.startswith('"') and t.endswith('"'):
                t = t[1:-1]
            out.append(f'"{t}"')
        return " ".join(out)

    def _snippet_for(self, path: str, query: str, content: str) -> str:
        cache_key = (path, query)
        cached = self._snippet_cache.get(cache_key)
        if cached is not None:
            return cached
        max_bytes = 200_000
        try:
            if getattr(self.db, "settings", None):
                max_bytes = int(getattr(self.db.settings, "SNIPPET_MAX_BYTES", max_bytes))
        except Exception:
            pass
        if len(content) > max_bytes:
            content = content[:max_bytes]
        snippet = snippet_around(content, [query], 3, highlight=True)
        cache_size = 128
        try:
            if getattr(self.db, "settings", None):
                cache_size = int(getattr(self.db.settings, "SNIPPET_CACHE_SIZE", cache_size))
        except Exception:
            pass
        if cache_size > 0:
            self._snippet_cache[cache_key] = snippet
            self._snippet_lru.append(cache_key)
            while len(self._snippet_lru) > cache_size:
                old = self._snippet_lru.pop(0)
                self._snippet_cache.pop(old, None)
        return snippet

    def repo_candidates(self, q: str, limit: int = 3, root_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        q = (q or "").strip()
        if not q:
            return []
        root_id = list(root_ids)[0] if root_ids else None
        sql = "SELECT repo, COUNT(1) as c FROM files"
        sql, params = self.db.apply_root_filter(sql, root_id)
        sql += " AND (path LIKE ? OR rel_path LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
        sql += " GROUP BY repo ORDER BY c DESC LIMIT ?"
        params.append(limit)
        cur = self.db._get_conn().cursor()
        cur.execute(sql, params)
        return [{"repo": r[0], "score": int(r[1]), "evidence": ""} for r in cur.fetchall()]
