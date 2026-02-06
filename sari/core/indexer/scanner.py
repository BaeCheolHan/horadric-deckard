import fnmatch
import os
import re
from pathlib import Path
from typing import Iterable, List, Tuple, Optional
from sari.core.utils.gitignore import GitignoreMatcher
from sari.core.utils.path_trie import PathTrie

class Scanner:
    def __init__(self, cfg, active_workspaces: Optional[List[str]] = None):
        self.cfg = cfg
        from sari.core.settings import settings as global_settings
        self.settings = getattr(self.cfg, "settings", None) or global_settings
        self.max_depth = self.settings.MAX_DEPTH
        
        # 1. Hardcoded Directory Excludes (Exact Match)
        self.hard_exclude_dirs = {
            ".git", "node_modules", ".venv", "venv", "dist", "build", 
            ".next", "target", "coverage", ".idea", ".vscode", ".pytest_cache",
            "__pycache__", ".DS_Store"
        }
        
        # 2. Hardcoded File Excludes (Glob Match)
        self.hard_exclude_globs = {
            "*.pyc", "*.pyo", "*.pyd", "*.class", "*.obj", "*.o", 
            "*.dll", "*.so", "*.dylib", "*.exe", "*.bin"
        }
        
        # Pre-calculate filters
        self.include_ext = {e.lower() for e in getattr(self.cfg, "include_ext", [])}
        self.include_files = set(getattr(self.cfg, "include_files", []))
        self.include_all = not self.include_ext and not self.include_files
        self.follow_symlinks = getattr(self.cfg.settings, "FOLLOW_SYMLINKS", False)

        # O(1) match optimization
        user_exclude_dirs = set(getattr(self.cfg, "exclude_dirs", []))
        self.exclude_dir_regex = self._compile_patterns(user_exclude_dirs | self.hard_exclude_dirs)
        
        user_exclude_globs = set(getattr(self.cfg, "exclude_globs", []))
        self.exclude_glob_regex = self._compile_patterns(user_exclude_globs | self.hard_exclude_globs)

        # Build Trie for O(L) overlap detection
        self.workspace_trie = PathTrie()
        if active_workspaces:
            for ws in active_workspaces:
                self.workspace_trie.insert(ws)

    def _compile_patterns(self, patterns: Iterable[str]) -> Optional[re.Pattern]:
        """Correctly compile glob patterns into a single optimized regex."""
        if not patterns: return None
        regex_parts = []
        for pat in patterns:
            # ALWAYS use fnmatch.translate for glob semantics
            regex_parts.append(fnmatch.translate(pat))
        return re.compile("|".join(regex_parts))

    def iter_file_entries(self, root: Path, apply_exclude: bool = True) -> Iterable[Tuple[Path, os.stat_result, bool]]:
        yield from self._scan_recursive(root, root, depth=0, follow_symlinks=self.follow_symlinks, apply_exclude=apply_exclude, visited=set())

    def _scan_recursive(self, root: Path, current_dir: Path, depth: int, follow_symlinks: bool, apply_exclude: bool, visited: set) -> Iterable[Tuple[Path, os.stat_result, bool]]:
        if depth > self.max_depth:
            return

        # 1. Skip sub-directories managed by another ACTIVE workspace.
        # Boundary is registry/trie-driven, not marker-file driven.
        if current_dir != root:
            if self.workspace_trie.is_path_owned_by_sub_workspace(str(current_dir), str(root)):
                return

        # Cycle detection for symlinks
        if follow_symlinks:
            try:
                real_path = str(current_dir.resolve())
                if real_path in visited:
                    return
                visited.add(real_path)
            except (PermissionError, OSError):
                return

        # gitignore check
        gitignore_lines = list(getattr(self.cfg, "gitignore_lines", []))
        gitignore = GitignoreMatcher(gitignore_lines) if gitignore_lines else None

        try:
            entries = list(os.scandir(current_dir))
        except (PermissionError, OSError):
            return

        for entry in entries:
            try:
                p = Path(entry.path)
                rel = str(p.absolute().relative_to(root))
            except:
                continue

            if entry.is_dir(follow_symlinks=follow_symlinks):
                # Directory processing
                d_name = entry.name
                if apply_exclude:
                    if self.exclude_dir_regex and (self.exclude_dir_regex.match(d_name) or self.exclude_dir_regex.match(rel)):
                        continue
                    if gitignore and gitignore.is_ignored(rel.replace(os.sep, "/"), is_dir=True):
                        continue
                
                yield from self._scan_recursive(root, p, depth + 1, follow_symlinks, apply_exclude, visited)
            
            elif entry.is_file(follow_symlinks=follow_symlinks):
                # File processing
                fn = entry.name
                excluded = False
                if self.exclude_glob_regex and (self.exclude_glob_regex.match(fn) or self.exclude_glob_regex.match(rel)):
                    excluded = True
                
                if not excluded and gitignore:
                    rel_posix = rel.replace(os.sep, "/")
                    if gitignore.is_ignored(rel_posix, is_dir=False):
                        excluded = True
                
                if not excluded and self.exclude_dir_regex:
                    rel_parts = rel.split(os.sep)
                    for part in rel_parts:
                        if self.exclude_dir_regex.match(part):
                            excluded = True
                            break
                
                try: st = entry.stat(follow_symlinks=follow_symlinks)
                except: continue

                # Include filter
                if not self.include_all:
                    rel_posix = rel.replace(os.sep, "/")
                    ext = p.suffix.lower()
                    included = False
                    if self.include_files:
                        for pattern in self.include_files:
                            if fnmatch.fnmatch(fn, pattern) or fnmatch.fnmatch(rel_posix, pattern):
                                included = True
                                break
                    if not included and self.include_ext and ext in self.include_ext:
                        included = True
                    if not included:
                        continue

                if apply_exclude and excluded: continue
                yield p, st, excluded
