import fnmatch
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

# Support script mode and package mode
try:
    from .config import Config  # type: ignore
    from .db import LocalSearchDB  # type: ignore
except ImportError:
    from config import Config  # type: ignore
    from db import LocalSearchDB  # type: ignore

# Add logging support
if False: # Type checking only
    from .telemetry import TelemetryLogger



@dataclass
class IndexStatus:
    index_ready: bool = False
    last_scan_ts: float = 0.0
    scanned_files: int = 0
    indexed_files: int = 0
    errors: int = 0


_REDACT_PATTERNS = [
    # key=value / key: value (line-based assignments)
    re.compile(
        r"(?im)^(\s*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret|private[_-]?key|refresh[_-]?token|id[_-]?token|session[_-]?token|aws[_-]?secret[_-]?access[_-]?key)\s*[:=]\s*)(.+?)\s*$"
    ),
    # common spring property style: xxx.password=...
    re.compile(
        r"(?im)^(\s*[\w\.-]*(?:password|secret|token|api[_-]?key|client[_-]?secret|private[_-]?key|aws[_-]?secret[_-]?access[_-]?key)[\w\.-]*\s*=\s*)(.+?)\s*$"
    ),
    # JSON style: "password": "..." (or token/apiKey/...)
    re.compile(
        r"(?im)^(\s*\"(?:password|secret|token|api[_-]?key|client[_-]?secret|private[_-]?key|refresh[_-]?token|id[_-]?token|session[_-]?token|aws[_-]?secret[_-]?access[_-]?key)\"\s*:\s*)\"(.*?)\"(\s*,?\s*)$"
    ),
    # Authorization header: Authorization: Bearer <token>
    re.compile(r"(?im)^(\s*authorization\s*:\s*bearer\s+)(.+?)\s*$"),
    # Inline Bearer token patterns (defensive; keep narrow)
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-\._~\+/]+=*"),
]


def _redact(text: str) -> str:
    # Keep this conservative: only redact obvious assignments.
    for pat in _REDACT_PATTERNS:
        # JSON pattern has 3 groups: prefix, value, suffix.
        if pat.groups == 3:
            text = pat.sub(lambda m: f"{m.group(1)}\"***\"{m.group(3)}", text)
            continue
        # Most patterns: group(1)=prefix, group(2)=value
        if pat.groups >= 1:
            text = pat.sub(lambda m: f"{m.group(1)}***", text)
    return text


class Indexer:
    def __init__(self, cfg: Config, db: LocalSearchDB, logger=None):
        self.cfg = cfg
        self.db = db
        self.logger = logger
        self.status = IndexStatus()
        self._stop = threading.Event()
        self._rescan = threading.Event()
        self._root_repo_name = "__root__"

    def stop(self) -> None:
        self._stop.set()
        self._rescan.set()

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

    def _scan_once(self) -> None:
        root = Path(os.path.expanduser(self.cfg.workspace_root)).resolve()
        
        if self.logger:
            self.logger.log_info(f"Starting scan of {root}")

        if not root.exists() or not root.is_dir():
            self.status.errors += 1
            if self.logger:
                self.logger.log_error(f"Root path does not exist: {root}")
            return

        # 1. Collect all candidate files with stat info for prioritization
        file_entries = []
        for file_path in self._iter_files(root):
            try:
                st = file_path.stat()
                if st.st_size > self.cfg.max_file_bytes:
                    continue
                file_entries.append((file_path, st))
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Error accessing file {file_path}: {e}")
                continue
        
        if self.logger:
            self.logger.log_info(f"Scan found {len(file_entries)} candidates")
        
        # 2. Prioritize: Recent files first + Core files (v2.5.0)
        now = time.time()
        def sort_key(entry):
            path, st = entry
            rel_lower = str(path.relative_to(root)).lower()
            score = st.st_mtime # Base: mtime
            # Priority Boost: Core metadata files
            if any(p in rel_lower for p in ["agents.md", "gemini.md", "service.json", "repo.yaml"]):
                score += 10**9 # Future boost
            return score

        file_entries.sort(key=sort_key, reverse=True)

        # 3. Process files with Smart Delta Scan & AI Safety Net
        scanned = 0
        indexed = 0
        batch: List[Tuple[str, str, int, int, str]] = []
        batch_size = max(50, int(getattr(self.cfg, "commit_batch_size", 500)))

        for file_path, st in file_entries:
            scanned += 1
            try:
                rel = str(file_path.relative_to(root))
                # Repo = 1depth subdirectory; root-level files use a dedicated repo name
                if os.sep not in rel:
                    repo = self._root_repo_name
                else:
                    repo = rel.split(os.sep, 1)[0]
                if not repo:
                    continue

                # Smart Delta Scan: Check mtime & size
                prev = self.db.get_file_meta(rel)
                is_changed = True
                if prev is not None:
                    prev_mtime, prev_size = prev
                    # Meta match?
                    if int(st.st_mtime) == int(prev_mtime) and int(st.st_size) == int(prev_size):
                        # AI Safety Net: If modified within last 3 seconds, force re-index
                        if now - st.st_mtime > 3.0:
                            is_changed = False
                            # DEBUG: Log skipped file
                            # if self.logger and scanned % 100 == 0:
                            #     self.logger.log_info(f"Skipping unchanged file: {rel}")
                else:
                    if self.logger:
                        self.logger.log_info(f"New file detected: {rel}")
                
                if not is_changed:
                    continue

                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                if getattr(self.cfg, "redact_enabled", True):
                    text = _redact(text)

                # Process meta files (v2.4.3)
                fn = file_path.name.lower()
                if fn in ("service.json", "repo.yaml", "package.json"):
                    self._process_meta_file(file_path, repo)

                batch.append((rel, repo, int(st.st_mtime), int(st.st_size), text))

                if len(batch) >= batch_size:
                    self.db.upsert_files(batch)
                    indexed += len(batch)
                    batch.clear()

            except Exception as e:
                self.status.errors += 1
                if self.logger:
                    self.logger.log_error(f"Error indexing file {file_path}: {e}")

        if batch:
            try:
                self.db.upsert_files(batch)
                indexed += len(batch)
            except Exception as e:
                self.status.errors += 1
                if self.logger:
                    self.logger.log_error(f"Error flushing batch: {e}")

        # DEBUG: Log DB Stats
        try:
            db_status = self.db.get_index_status()
            if self.logger:
                self.logger.log_info(f"DB Stats after scan - Total Files: {db_status.get('total_files')}")
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Failed to get DB stats: {e}")

        self.db.clear_stats_cache()
        self.status.last_scan_ts = time.time()
        self.status.scanned_files = scanned
        self.status.indexed_files = indexed
        
        if self.logger:
            self.logger.log_info(f"Scan complete. Scanned: {scanned}, Indexed: {indexed}, Errors: {self.status.errors}")

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
        except Exception:
            pass

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
