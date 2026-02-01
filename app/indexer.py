import concurrent.futures
import fnmatch
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple, Optional, Any

# Support script mode and package mode
try:
    from .config import Config  # type: ignore
    from .db import LocalSearchDB  # type: ignore
except ImportError:
    from config import Config  # type: ignore
    from db import LocalSearchDB  # type: ignore

# === Constants ===
CORE_FILE_BOOST = 10**9  # Priority boost for core metadata files
AI_SAFETY_NET_SECONDS = 3.0  # Force re-index if modified within this window



@dataclass
class IndexStatus:
    index_ready: bool = False
    last_scan_ts: float = 0.0
    scanned_files: int = 0
    indexed_files: int = 0
    errors: int = 0


_REDACT_PATTERNS = [
    # key=value / key: value (assignments)
    re.compile(
        r"(?i)(\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret|private[_-]?key|refresh[_-]?token|id[_-]?token|session[_-]?token|aws[_-]?secret(?:[_-]?access[_-]?key)?|database[_-]?url|openai[_-]?api[_-]?key)\s*[:=]\s*)([\"']?)(.+?)\2(?=[,\s]|$)"
    ),
    # JSON style: "password": "..."
    re.compile(
        r"(?i)(\"(?:password|secret|token|api[_-]?key|client[_-]?secret|private[_-]?key|refresh[_-]?token|id[_-]?token|session[_-]?token|aws[_-]?secret(?:[_-]?access[_-]?key)?|database[_-]?url|openai[_-]?api[_-]?key)\"\s*:\s*)(\")(.*?)(\")"
    ),
    # Authorization header: Authorization: Bearer <token>
    re.compile(r"(?im)^(\s*authorization\s*:\s*bearer\s+)(.+?)\s*$"),
]

# Symbol patterns removed in v2.7.0 in favor of block-aware parser in _extract_symbols


def _redact(text: str) -> str:
    # Use a more robust approach for multiple matches
    # Masking group index depends on the pattern
    
    # 1. Assignments and JSON style
    for pat in _REDACT_PATTERNS[:2]:
        text = pat.sub(r"\1\2***\2", text)
    
    # 2. Authorization header (Line based)
    text = _REDACT_PATTERNS[2].sub(r"\1***", text)
    
    # 3. Inline Bearer (Catch-all)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9\-\._~\+/]+=*", r"\1***", text)
    
    return text


def _extract_symbols(path: str, content: str) -> List[Tuple[str, str, str, int, int, str, str]]:
    """
    Extract symbols with start/end lines (v2.7.0).
    Returns: (path, name, kind, line, end_line, content, parent_name)
    """
    ext = Path(path).suffix.lower()
    symbols = []
    lines = content.splitlines()
    total_lines = len(lines)
    
    # 1. Indentation-based languages (Python)
    if ext in (".py",):
        # Regex for Python definitions
        pat = re.compile(r"^(\s*)(class|def|async\s+def)\s+([a-zA-Z_][a-zA-Z0-9_]*)")
        
        stack = [] # (indent_level, symbol_info_dict)
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip empty lines or comments for indent calculation if needed
            if not stripped: 
                continue
            
            # Simple indent check
            indent = len(line) - len(line.lstrip())
            
            # Check for block ends: if current indent <= stack's indent, those blocks finished
            while stack and indent <= stack[-1][0]:
                lvl, info = stack.pop()
                info["end_line"] = i # The line BEFORE this current line was the end. 
                # (Actually if i is start of new block, previous block ended at i-1. 
                # But let's say it covers until start of next sibling)
                symbols.append(info)
            
            match = pat.match(line)
            if match:
                s_indent = match.group(1)
                s_type = match.group(2).replace("async ", "")
                s_name = match.group(3)
                indent_len = len(s_indent)
                
                # Determine parent
                parent = ""
                if stack:
                    parent = stack[-1][1]["name"]
                
                info = {
                    "path": path,
                    "name": s_name,
                    "kind": "method" if parent and s_type == "def" else s_type,
                    "line": i + 1,
                    "end_line": i + 1, # Default if no children or EOF
                    "content": stripped,
                    "parent_name": parent
                }
                stack.append((indent_len, info))
                
        # Close remaining stack at EOF
        while stack:
            lvl, info = stack.pop()
            info["end_line"] = total_lines
            symbols.append(info)
            
    # 2. Brace-based languages (JS, TS, Java, Go, Rust, C++)
    elif ext in (".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".cpp", ".c"):
        # Simplified parser: track curly braces
        patterns = []
        if ext == ".go":
            patterns.append((re.compile(r"func\s+([a-zA-Z0-9_]+)\("), "function"))
            patterns.append((re.compile(r"type\s+([a-zA-Z0-9_]+)\s+struct"), "struct"))
            patterns.append((re.compile(r"type\s+([a-zA-Z0-9_]+)\s+interface"), "interface"))
        elif ext == ".rs":
            patterns.append((re.compile(r"fn\s+([a-zA-Z0-9_]+)"), "function"))
            patterns.append((re.compile(r"struct\s+([a-zA-Z0-9_]+)"), "struct"))
            patterns.append((re.compile(r"enum\s+([a-zA-Z0-9_]+)"), "enum"))
            patterns.append((re.compile(r"impl\s+([a-zA-Z0-9_]+)"), "impl"))
        else:
            # JS/TS/Java
            patterns.append((re.compile(r"class\s+([a-zA-Z0-9_]+)"), "class"))
            patterns.append((re.compile(r"interface\s+([a-zA-Z0-9_]+)"), "interface"))
            # Functions in JS/TS often 'function foo()' or 'const foo = () =>'
            patterns.append((re.compile(r"function\s+([a-zA-Z0-9_]+)"), "function"))
        
        active_symbols = [] # (brace_balance_at_start, info)
        current_balance = 0
        
        for i, line in enumerate(lines):
            # Update brace balance (naive)
            open_c = line.count('{')
            close_c = line.count('}')
            
            # Check for new symbols
            for pat, kind in patterns:
                m = pat.search(line)
                if m:
                    name = m.group(1)
                    info = {
                        "path": path,
                        "name": name,
                        "kind": kind,
                        "line": i + 1,
                        "end_line": i + 1,
                        "content": line.strip(),
                        "parent_name": "" 
                    }
                    # It starts at current_balance
                    active_symbols.append([current_balance, info])
                    break
            
            current_balance += (open_c - close_c)
            
            # Check for closed symbols
            still_active = []
            for start_bal, info in active_symbols:
                # If balance drops back to start blocks (or below), it's closed
                if current_balance <= start_bal and (open_c > 0 or close_c > 0):
                    info["end_line"] = i + 1
                    symbols.append(info)
                else:
                    still_active.append([start_bal, info])
            active_symbols = still_active

        # Close remainder
        for _, info in active_symbols:
            info["end_line"] = total_lines
            symbols.append(info)

    # Output formatting
    result_tuples = []
    for s in symbols:
        result_tuples.append((
            s["path"], s["name"], s["kind"], s["line"], s["end_line"], s["content"], s.get("parent_name", "")
        ))
    return result_tuples


class Indexer:
    def __init__(self, cfg: Config, db: LocalSearchDB, logger=None):
        self.cfg = cfg
        self.db = db
        self.logger = logger
        self.status = IndexStatus()
        self._stop = threading.Event()
        self._rescan = threading.Event()
        self._root_repo_name = "__root__"
        # v2.6.0: Thread pool for parallel processing
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 4) * 4))

    def stop(self) -> None:
        self._stop.set()
        self._rescan.set()
        self._executor.shutdown(wait=False)

    def request_rescan(self) -> None:
        """Trigger an immediate scan outside the normal interval."""
        self._rescan.set()

    def run_forever(self) -> None:
        # first scan ASAP
        self._scan_once()
        self.status.index_ready = True

        while not self._stop.is_set():
            # Wait for either a rescan request or the interval.
            self._rescan.wait(timeout=max(1, int(self.cfg.scan_interval_seconds)))
            self._rescan.clear()
            if self._stop.is_set():
                break
            self._scan_once()

    def _process_file_task(self, root: Path, file_path: Path, st: os.stat_result, scan_ts: int, now: float) -> Optional[dict]:
        """Task to be run in thread pool. Returns dict of data to upsert or None."""
        try:
            rel = str(file_path.relative_to(root))
            # Repo = 1depth subdirectory; root-level files use a dedicated repo name
            if os.sep not in rel:
                repo = self._root_repo_name
            else:
                repo = rel.split(os.sep, 1)[0]
            if not repo:
                return None

            # Smart Delta Scan: Check mtime & size
            prev = self.db.get_file_meta(rel)
            is_changed = True
            if prev is not None:
                prev_mtime, prev_size = prev
                # Meta match?
                if int(st.st_mtime) == int(prev_mtime) and int(st.st_size) == int(prev_size):
                    # AI Safety Net: If modified within safety window, force re-index
                    if now - st.st_mtime > AI_SAFETY_NET_SECONDS:
                        is_changed = False
            
            if not is_changed:
                return {"type": "unchanged", "rel": rel}

            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                # v2.5.3: If read fails but file exists, still mark as seen to prevent immediate deletion
                if self.logger:
                    self.logger.log_info(f"Read failed for {file_path}, deferring deletion: {e}")
                return {"type": "unchanged", "rel": rel}

            if getattr(self.cfg, "redact_enabled", True):
                text = _redact(text)

            # Process meta files (v2.4.3) - Side effect in main thread? 
            # Ideally DB writes should be main thread or locked. 
            # We return meta info and let main thread write it.
            # But process_meta_file writes to DB. Let's do it here, DB is thread-safe(ish) with locks, 
            # but we prefer batching. 
            # Let's just return the data.
            meta_data = None
            fn = file_path.name.lower()
            if fn in ("service.json", "repo.yaml", "package.json"):
                meta_data = {"path": str(file_path), "repo": repo}

            symbols = _extract_symbols(rel, text)

            return {
                "type": "changed",
                "rel": rel,
                "repo": repo,
                "mtime": int(st.st_mtime),
                "size": int(st.st_size),
                "content": text,
                "scan_ts": scan_ts,
                "meta_data": meta_data,
                "symbols": symbols
            }

        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Error indexing file {file_path}: {e}")
            return None

    def _process_meta_file(self, file_path: Path, repo: str) -> None:
        """Extract metadata from config files (v2.4.3)."""
        tags = []
        domain = ""
        description = ""
        
        try:
            name = file_path.name.lower()
            if name == "service.json":
                data = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
                tags = data.get("tags", [])
                domain = data.get("domain", "")
                description = data.get("description", "")
            elif name == "repo.yaml":
                # Basic line parsing for yaml to avoid dependency
                text = file_path.read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k, v = k.strip().lower(), v.strip().strip('"').strip("'")
                        if k == "domain": domain = v
                        elif k == "description": description = v
                        elif k == "tags":
                            tags = [t.strip() for t in v.strip("[]").split(",")]
            elif name == "package.json":
                data = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
                description = data.get("description", "")
                if "keywords" in data:
                    tags = data.get("keywords", [])

            if tags or domain or description:
                tag_str = ",".join(tags) if isinstance(tags, list) else str(tags)
                self.db.upsert_repo_meta(repo, tags=tag_str, domain=domain, description=description)
        except Exception as e:
            # Log parsing errors at debug level for troubleshooting
            if self.logger:
                self.logger.log_info(f"Failed to parse meta file {file_path.name}: {e}")

    def _iter_files(self, root: Path) -> Iterable[Path]:
        include_ext = set((self.cfg.include_ext or []))
        include_files = set((self.cfg.include_files or []))
        exclude_dirs = set((self.cfg.exclude_dirs or []))
        exclude_globs = list((getattr(self.cfg, "exclude_globs", []) or []))

        for dirpath, dirnames, filenames in os.walk(root):
            # prune excluded dirs (in-place)
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]

            for fn in filenames:
                # v2.5.0: Explicitly exclude root-level CLI entry points from index
                # to prevent __root__ from appearing as a repo candidate.
                if fn in ("AGENTS.md", "GEMINI.md", "README.md", "install.sh", "uninstall.sh"):
                    # Only skip if we are strictly at the root
                    if os.path.samefile(dirpath, root):
                         continue

                # Fast path filename-only excludes
                if exclude_globs and any(fnmatch.fnmatch(fn, g) for g in exclude_globs):
                    continue

                p = Path(dirpath) / fn
                rel = str(p.relative_to(root))
                if exclude_globs and any(fnmatch.fnmatch(rel, g) for g in exclude_globs):
                    continue

                if include_files and fn in include_files:
                    yield p
                    continue

                if include_ext:
                    suf = p.suffix.lower()
                    if suf in include_ext:
                        yield p

    def _scan_once(self) -> None:
        root = Path(os.path.expanduser(self.cfg.workspace_root)).resolve()
        
        if not root.exists() or not root.is_dir():
            self.status.errors += 1
            if self.logger:
                self.logger.log_error(f"Root path does not exist: {root}")
            return

        # 1. Collect all candidate files with stat info for prioritization
        file_entries = []
        for file_path in self._iter_files(root):
            try:
                # v2.5.4: Security - Skip symlinks pointing outside the workspace
                if file_path.is_symlink():
                    try:
                        resolved = file_path.resolve()
                        if not resolved.is_relative_to(root):
                            if self.logger:
                                self.logger.log_info(f"Skipping external symlink: {file_path}")
                            continue
                    except (OSError, RuntimeError, ValueError):
                        # ValueError can be raised by is_relative_to if paths are on different drives
                        continue

                st = file_path.stat()
                if st.st_size > self.cfg.max_file_bytes:
                    continue
                file_entries.append((file_path, st))
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Error accessing file {file_path}: {e}")
                continue
        
        # 2. Prioritize: Recent files first + Core files (v2.5.0)
        now = time.time()
        def sort_key(entry):
            path, st = entry
            rel_lower = str(path.relative_to(root)).lower()
            score = st.st_mtime # Base: mtime
            # Priority Boost: Core metadata files
            if any(p in rel_lower for p in ["agents.md", "gemini.md", "service.json", "repo.yaml"]):
                score += CORE_FILE_BOOST
            return score

        file_entries.sort(key=sort_key, reverse=True)

        # 3. Process files with ThreadPool
        scanned = 0
        indexed = 0
        batch: List[Tuple[str, str, int, int, str, int]] = []
        batch: List[Tuple[str, str, int, int, str, int]] = []
        symbols_batch: List[Tuple[str, str, str, int, int, str, str]] = []
        unchanged_batch: List[str] = []
        unchanged_batch: List[str] = []
        batch_size = max(50, int(getattr(self.cfg, "commit_batch_size", 500)))
        scan_ts = int(time.time())

        futures = []
        for file_path, st in file_entries:
            futures.append(self._executor.submit(self._process_file_task, root, file_path, st, scan_ts, now))
        
        # Process results as they complete
        for future in concurrent.futures.as_completed(futures):
            scanned += 1
            result = future.result()
            if result is None:
                self.status.errors += 1
                continue
            
            if result["type"] == "unchanged":
                unchanged_batch.append(result["rel"])
                if len(unchanged_batch) >= batch_size:
                    self.db.update_last_seen(unchanged_batch, scan_ts)
                    unchanged_batch.clear()
            
            elif result["type"] == "changed":
                # Handle meta files if any
                if result.get("meta_data"):
                    # We still do this synchronously per file, it's rare
                    md = result["meta_data"]
                    try:
                        self._process_meta_file(Path(md["path"]), md["repo"])
                    except Exception:
                        pass

                batch.append((
                    result["rel"], 
                    result["repo"], 
                    result["mtime"], 
                    result["size"], 
                    result["content"], 
                    result["scan_ts"]
                ))
                
                if result.get("symbols"):
                    symbols_batch.extend(result["symbols"])

                if len(batch) >= batch_size:
                    self.db.upsert_files(batch)
                    # Upsert symbols too
                    if symbols_batch:
                        self.db.upsert_symbols(symbols_batch)
                        symbols_batch.clear()
                        
                    indexed += len(batch)
                    batch.clear()
        
        # Flush remainders
        if batch:
            try:
                self.db.upsert_files(batch)
                indexed += len(batch)
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Error flushing batch: {e}")
        
        if symbols_batch:
            try:
                self.db.upsert_symbols(symbols_batch)
            except Exception as e:
                pass # Non-critical

        if unchanged_batch:
            try:
                self.db.update_last_seen(unchanged_batch, scan_ts)
            except Exception as e:
                 if self.logger:
                    self.logger.log_error(f"Error updating unchanged files: {e}")

        # 4. Handle Deletions (v2.5.3: Optimized with last_seen)
        try:
            count = self.db.delete_unseen_files(scan_ts)
            if count > 0 and self.logger:
                self.logger.log_info(f"Removed {count} deleted files from index")
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Error checking for deleted files: {e}")


        self.db.clear_stats_cache()
        self.status.last_scan_ts = time.time()
        self.status.scanned_files = scanned
        self.status.indexed_files = indexed
