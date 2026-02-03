import sqlite3
import re
import time
from pathlib import Path
from typing import List, Tuple, Optional, Any, Dict

from .models import SearchHit, SearchOptions
from .ranking import (
    extract_terms, count_matches, calculate_recency_score, 
    snippet_around, get_file_extension, glob_to_like
)

class SearchEngine:
    def __init__(self, db):
        self.db = db

    def search_v2(self, opts: SearchOptions) -> Tuple[List[SearchHit], Dict[str, Any]]:
        """Enhanced search with Hybrid (Symbol + FTS) strategy."""
        q = (opts.query or "").strip()
        if not q:
            return [], {"fallback_used": False, "total_scanned": 0, "total": 0}

        terms = extract_terms(q)
        meta: Dict[str, Any] = {"fallback_used": False, "total_scanned": 0}
        
        # Regex mode bypasses hybrid logic
        if opts.use_regex:
            return self._search_regex(opts, terms, meta)
        
        # 1. Symbol Search (Priority Layer)
        symbol_hits_data = []
        if opts.total_mode != "approx":
             symbol_hits_data = self.db.search_symbols(q, repo=opts.repo, limit=50)

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
                file_type=get_file_extension(s["path"]),
                hit_reason=f"Symbol: {s['kind']} {s['name']}",
                context_symbol=f"{s['kind']}: {s['name']}",
                docstring=s.get("docstring", ""),
                metadata=s.get("metadata", "{}")
            )
            # Recency boost if enabled
            if opts.recency_boost:
                hit.score = calculate_recency_score(hit.mtime, hit.score)
            symbol_hits.append(hit)

        # 2. FTS Search
        fts_hits = []
        # v2.7.0: Allow unicode in FTS, but fallback if non-ASCII character present
        # as FTS tokenizers often skip emojis and special symbols.
        has_unicode = any(ord(c) > 127 for c in q)
        is_too_short = len(q) < 3
        
        use_fts = self.db.fts_enabled and not is_too_short and not has_unicode
        fts_success = False

        
        if use_fts:
            try:
                res = self.db._search_fts(opts, terms, meta, no_slice=True)
                if res:
                    fts_hits, fts_meta = res
                    meta.update(fts_meta)
                    fts_success = True
            except sqlite3.OperationalError:
                pass
        
        if not fts_success:
            # Fallback to LIKE
            res, like_meta = self.db._search_like(opts, terms, meta, no_slice=True)
            fts_hits = res
            meta.update(like_meta)
            meta["fallback_used"] = True 
        elif not fts_hits and terms:
            # v2.7.5: Force fallback if FTS results are suspiciously empty for non-trivial query
            res, like_meta = self.db._search_like(opts, terms, meta, no_slice=True)
            fts_hits = res
            meta.update(like_meta)
            meta["fallback_used"] = True

        # 3. Merge Strategies
        merged_map: Dict[str, SearchHit] = {}
        for h in fts_hits:
            merged_map[h.path] = h
            
        for sh in symbol_hits:
            if sh.path in merged_map:
                existing = merged_map[sh.path]
                existing.score += 1200.0 
                existing.hit_reason = f"{sh.hit_reason}, {existing.hit_reason}"
                if sh.snippet.strip() not in existing.snippet:
                     existing.snippet = f"{sh.snippet}\n...\n{existing.snippet}"
                if sh.docstring:
                    existing.docstring = sh.docstring
                if sh.metadata and sh.metadata != "{}":
                    existing.metadata = sh.metadata
            else:
                merged_map[sh.path] = sh
                
        final_hits = list(merged_map.values())
        final_hits.sort(key=lambda h: (-h.score, -h.mtime, h.path))
        
        start = int(opts.offset)
        end = start + int(opts.limit)
        
        # Adjust Total Count
        if opts.total_mode == "approx":
             meta["total"] = -1
        elif meta.get("total", 0) > 0:
             meta["total"] = max(meta["total"], len(final_hits))
        else:
             meta["total"] = len(final_hits)
             
        return final_hits[start:end], meta

    def _search_like(self, opts: SearchOptions, terms: List[str], 
                     meta: Dict[str, Any], no_slice: bool = False) -> Tuple[List[SearchHit], Dict[str, Any]]:
        meta["fallback_used"] = True
        like_q = opts.query.replace("^", "^^").replace("%", "^%").replace("_", "^_")
        # v2.7.0: Use files_view (fv) instead of files (f) for content match as it's decompressed
        where_clauses = ["(fv.content LIKE ? ESCAPE '^' OR f.path LIKE ? ESCAPE '^' OR f.repo LIKE ? ESCAPE '^')"]
        params: List[Any] = [f"%{like_q}%", f"%{like_q}%", f"%{like_q}%"]
        
        filter_clauses, filter_params = self._build_filter_clauses(opts)
        where_clauses.extend(filter_clauses)
        params.extend(filter_params)
        
        where = " AND ".join(where_clauses)
        fetch_limit = (opts.offset + opts.limit) * 2
        if fetch_limit < 100: fetch_limit = 100
        
        sql = f"""
            SELECT f.repo AS repo,
                   f.path AS path,
                   f.mtime AS mtime,
                   f.size AS size,
                   1.0 AS score,
                   fv.content AS content
            FROM files f
            JOIN files_view fv ON f.rowid = fv.rowid
            WHERE {where}
            ORDER BY {"f.mtime DESC" if opts.recency_boost else "f.path"}, f.path ASC
            LIMIT ?;
        """
        params.append(int(fetch_limit))

        with self.db._read_lock:
            if opts.total_mode == "exact":
                count_sql = f"SELECT COUNT(*) as c FROM files f JOIN files_view fv ON f.rowid = fv.rowid WHERE {where}"
                count_row = self.db._read.execute(count_sql, params[:-1]).fetchone()
                meta["total"] = int(count_row["c"]) if count_row else 0
            else:
                meta["total"] = -1
            
            rows = self.db._read.execute(sql, params).fetchall()

        meta["total_mode"] = opts.total_mode
        hits = self._process_rows(rows, opts, terms)
        meta["total_scanned"] = len(rows)
        
        if no_slice:
            return hits, meta

        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _search_fts(self, opts: SearchOptions, terms: List[str], 
                    meta: Dict[str, Any], no_slice: bool = False) -> Optional[Tuple[List[SearchHit], Dict[str, Any]]]:
        # v2.7.0: Safe FTS query escaping
        # Wrap terms in double quotes and escape existing quotes to prevent FTS5 syntax errors
        safe_terms = []
        for t in terms:
            clean_t = t.replace('"', '""')
            if clean_t:
                safe_terms.append(f'"{clean_t}"')
        
        fts_query = " ".join(safe_terms)
        if not fts_query:
            return [], meta

        where_clauses = ["files_fts MATCH ?"]
        params: List[Any] = [fts_query]
        
        filter_clauses, filter_params = self._build_filter_clauses(opts)
        where_clauses.extend(filter_clauses)
        params.extend(filter_params)
        
        where = " AND ".join(where_clauses)
        total_hits = 0
        if opts.total_mode == "exact":
            try:
                count_sql = f"SELECT COUNT(*) as c FROM files_fts JOIN files f ON f.rowid = files_fts.rowid WHERE {where}"
                with self.db._read_lock:
                    count_row = self.db._read.execute(count_sql, params).fetchone()
                total_hits = int(count_row["c"]) if count_row else 0
            except sqlite3.OperationalError:
                return None
        else:
            total_hits = -1 
            
        meta["total"] = total_hits
        meta["total_mode"] = opts.total_mode
        fetch_limit = 50 
        
        path_prior_sql = """
        CASE 
            WHEN f.path LIKE 'src/%' OR f.path LIKE '%/src/%' OR f.path LIKE 'app/%' OR f.path LIKE '%/app/%' OR f.path LIKE 'core/%' OR f.path LIKE '%/core/%' THEN 0.6
            WHEN f.path LIKE 'config/%' OR f.path LIKE '%/config/%' OR f.path LIKE 'domain/%' OR f.path LIKE '%/domain/%' OR f.path LIKE 'service/%' OR f.path LIKE '%/service/%' THEN 0.4
            WHEN f.path LIKE 'test/%' OR f.path LIKE '%/test/%' OR f.path LIKE 'tests/%' OR f.path LIKE '%/tests/%' OR f.path LIKE 'example/%' OR f.path LIKE '%/example/%' OR f.path LIKE 'dist/%' OR f.path LIKE '%/dist/%' OR f.path LIKE 'build/%' OR f.path LIKE '%/build/%' THEN -0.7
            ELSE 0.0
        END
        """
        
        filetype_prior_sql = """
        CASE
            WHEN f.path LIKE '%.py' OR f.path LIKE '%.ts' OR f.path LIKE '%.go' OR f.path LIKE '%.java' OR f.path LIKE '%.kt' THEN 0.3
            WHEN f.path LIKE '%.yaml' OR f.path LIKE '%.yml' OR f.path LIKE '%.json' THEN 0.15
            WHEN f.path LIKE '%.lock' OR f.path LIKE '%.min.js' OR f.path LIKE '%.map' THEN -0.8
            ELSE 0.0
        END
        """
        
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
        
        with self.db._read_lock:
            rows = self.db._read.execute(sql, params).fetchall()
        
        hits = self._process_rows(rows, opts, terms, is_rerank=True)
        meta["total_scanned"] = len(rows)
        
        if no_slice:
            return hits, meta

        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _search_regex(self, opts: SearchOptions, terms: List[str], 
                      meta: Dict[str, Any]) -> Tuple[List[SearchHit], Dict[str, Any]]:
        meta["regex_mode"] = True
        flags = 0 if opts.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(opts.query, flags)
        except re.error as e:
            meta["regex_error"] = str(e)
            return [], meta
        
        where_clauses = ["1=1"]
        params: List[Any] = []
        if opts.repo:
            where_clauses.append("f.repo = ?")
            params.append(opts.repo)
        
        filter_clauses, filter_params = self._build_filter_clauses(opts)
        where_clauses.extend(filter_clauses)
        params.extend(filter_params)
        
        where = " AND ".join(where_clauses)
        
        sql = f"""
            SELECT f.repo AS repo,
                   f.path AS path,
                   f.mtime AS mtime,
                   f.size AS size,
                   fv.content AS content
            FROM files f
            JOIN files_view fv ON f.rowid = fv.rowid
            WHERE {where}
            ORDER BY {"f.mtime DESC" if opts.recency_boost else "f.path"}
            LIMIT 5000;
        """
        with self.db._read_lock:
            rows = self.db._read.execute(sql, params).fetchall()
        meta["total_scanned"] = len(rows)
        
        # No more manual _decompress(r["content"]) needed here as it comes from fv.content
        hits: List[SearchHit] = []
        for r in rows:
            path = r["path"]
            content = r["content"] or ""
            
            if not self._matches_file_types(path, opts.file_types): continue
            if not self._matches_path_pattern(path, opts.path_pattern): continue
            if self._matches_exclude_patterns(path, opts.exclude_patterns): continue
            
            matches = pattern.findall(content)
            if not matches: continue
            
            match_count = len(matches)
            score = float(match_count)
            if opts.recency_boost:
                score = calculate_recency_score(int(r["mtime"]), score)
            
            snippet = snippet_around(content, [opts.query], opts.snippet_lines, highlight=True)
            hits.append(SearchHit(
                repo=r["repo"], path=path, score=score, snippet=snippet,
                mtime=int(r["mtime"]), size=int(r["size"]), match_count=match_count,
                file_type=get_file_extension(path)
            ))
        
        hits.sort(key=lambda h: (-h.score, -h.mtime, h.path))
        meta["total"] = len(hits)
        meta["total_mode"] = "approx"
        start = opts.offset
        end = opts.offset + opts.limit
        return hits[start:end], meta

    def _process_rows(self, rows: list, opts: SearchOptions, 
                      terms: List[str], is_rerank: bool = False) -> List[SearchHit]:
        hits: List[SearchHit] = []
        all_meta = self.db.get_all_repo_meta()
        query_terms = [t.lower() for t in terms]
        query_raw_lower = opts.query.lower()
        
        # v2.7.0: Local import of _decompress is no longer strictly needed if content comes from VIEW,
        # but let's keep it as a fallback in case raw rows are passed.
        from .db import _decompress

        def_patterns = []
        for term in query_terms:
            if len(term) < 3: continue 
            p = re.compile(rf"(class|def|function|struct|pub\s+fn|async\s+def|interface|type)\s+{re.escape(term)}\b", re.IGNORECASE)
            def_patterns.append(p)

        for r in rows:
            path = r["path"]
            repo_name = r["repo"]
            # Try to use 'content' as is (from view), fallback to decompress if it's BLOB
            content = r["content"]
            if isinstance(content, (bytes, bytearray)):
                content = _decompress(content)
            elif content is None:
                content = ""
            
            mtime = int(r["mtime"])
            size = int(r["size"])
            
            if not self._matches_file_types(path, opts.file_types): continue
            if not self._matches_path_pattern(path, opts.path_pattern): continue
            if self._matches_exclude_patterns(path, opts.exclude_patterns): continue
            
            score = float(r["score"]) if r["score"] is not None else 0.0
            reasons = []
            path_lower = path.lower()
            filename = path_lower.split("/")[-1]
            file_stem = Path(filename).stem.lower()

            if filename == query_raw_lower or file_stem == query_raw_lower:
                score += 2.0
                reasons.append("Exact filename match")
            elif query_raw_lower in file_stem:
                score += 1.2
                reasons.append("Filename stem match")
            elif path_lower.endswith(query_raw_lower):
                score += 1.0
                reasons.append("Path suffix match")
            
            for pat in def_patterns:
                if pat.search(content):
                    score += 1.5
                    reasons.append("Definition found")
                    break
            
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
                    if span < 100:
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
                score = calculate_recency_score(mtime, score)
            
            match_count = count_matches(content, opts.query, False, opts.case_sensitive)
            if opts.case_sensitive and match_count == 0: continue
            
            # v2.7.0: Debugging fallback logic - if no matches found via count_matches, log why
            if match_count == 0 and not opts.case_sensitive:
                # We expect non-case-sensitive to find things if LIKE found them
                pass 

            snippet = snippet_around(content, terms, opts.snippet_lines, highlight=True)
            context_symbol = ""
            first_line_match = re.search(r"L(\d+):", snippet)
            if first_line_match:
                start_line = int(first_line_match.group(1))
                ctx = self.db._get_enclosing_symbol(path, start_line)
                if ctx:
                    context_symbol = ctx
                    score += 0.2
            
            hits.append(SearchHit(
                repo=repo_name, path=path, score=round(score, 3), snippet=snippet,
                mtime=mtime, size=size, match_count=match_count, 
                file_type=get_file_extension(path),
                hit_reason=", ".join(reasons) if reasons else "Content match",
                context_symbol=context_symbol
            ))
        
        hits.sort(key=lambda h: (-h.score, -h.mtime, h.path))
        return hits

    def repo_candidates(self, q: str, limit: int = 3) -> List[Dict[str, Any]]:
        q = (q or "").strip()
        if not q: return []
        limit = max(1, min(int(limit), 5))

        if self.db.fts_enabled:
            sql = """
                SELECT f.repo AS repo, COUNT(1) AS c
                FROM files_fts JOIN files f ON f.rowid = files_fts.rowid
                WHERE files_fts MATCH ? GROUP BY f.repo ORDER BY c DESC LIMIT ?;
            """
            try:
                with self.db._read_lock:
                    rows = self.db._read.execute(sql, (q, limit)).fetchall()
                out: List[Dict[str, Any]] = []
                for r in rows:
                    repo = str(r["repo"])
                    c = int(r["c"])
                    hits, _ = self.search_v2(SearchOptions(query=q, repo=repo, limit=1))
                    evidence = hits[0].snippet.replace("\n", " ")[:200] if hits else ""
                    out.append({"repo": repo, "score": c, "evidence": evidence})
                return out
            except sqlite3.OperationalError: pass

        like_q = q.replace("^", "^^").replace("%", "^%").replace("_", "^_")
        sql = "SELECT repo, COUNT(1) AS c FROM files WHERE content LIKE ? ESCAPE '^' GROUP BY repo ORDER BY c DESC LIMIT ?;"
        with self.db._read_lock:
            rows = self.db._read.execute(sql, (f"%{like_q}%", limit)).fetchall()
        out = []
        for r in rows:
            repo, c = str(r["repo"]), int(r["c"])
            hits, _ = self.search_v2(SearchOptions(query=q, repo=repo, limit=1))
            evidence = hits[0].snippet.replace("\n", " ")[:200] if hits else ""
            out.append({"repo": repo, "score": c, "evidence": evidence})
        return out

    def _build_filter_clauses(self, opts: SearchOptions) -> Tuple[List[str], List[Any]]:
        clauses, params = [], []
        if opts.repo:
            clauses.append("f.repo = ?")
            params.append(opts.repo)
        if opts.file_types:
            type_clauses = []
            for ft in opts.file_types:
                ext = ft.lower().lstrip(".")
                type_clauses.append("f.path LIKE ?")
                params.append(f"%.{ext}")
            if type_clauses: clauses.append("(" + " OR ".join(type_clauses) + ")")
        if opts.path_pattern:
            clauses.append("f.path LIKE ?")
            params.append(glob_to_like(opts.path_pattern))
        return clauses, params

    def _matches_file_types(self, path: str, file_types: List[str]) -> bool:
        if not file_types: return True
        return get_file_extension(path) in [ft.lower().lstrip('.') for ft in file_types]
    
    def _matches_path_pattern(self, path: str, pattern: Optional[str]) -> bool:
        if not pattern: return True
        import fnmatch
        
        # Normalize slashes for consistency
        path = path.replace("\\", "/")
        pattern = pattern.replace("\\", "/")
        
        # If pattern is absolute, match exactly or prefix
        if pattern.startswith("/"):
             if path.startswith(pattern): return True
             return fnmatch.fnmatch(path, pattern)

        # Relative pattern: match end of path or segment
        # e.g. "src/main.py" should match "/users/.../src/main.py"
        
        if path.endswith("/" + pattern): return True
        if path == pattern: return True
        
        # Check glob
        if fnmatch.fnmatch(path, pattern): return True
        if fnmatch.fnmatch(path, f"*/{pattern}"): return True
        if fnmatch.fnmatch(path, f"*/{pattern}/*"): return True
        
        # Fallback to existing loose match
        return (fnmatch.fnmatch(path, f"**/{pattern}") or 
                fnmatch.fnmatch(path, f"{pattern}*"))
    
    def _matches_exclude_patterns(self, path: str, patterns: List[str]) -> bool:
        if not patterns: return False
        import fnmatch
        for p in patterns:
            if p in path or fnmatch.fnmatch(path, f"*{p}*"): return True
        return False
