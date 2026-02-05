import fnmatch
import os
from pathlib import Path
from typing import Iterable, List, Tuple, Optional
from sari.core.utils.gitignore import GitignoreMatcher

class Scanner:
    def __init__(self, cfg):
        self.cfg = cfg
        # Use centralized setting from Settings class
        # cfg.settings is expected to be an instance of Settings
        from sari.core.settings import settings as global_settings
        self.settings = getattr(self.cfg, "settings", None) or global_settings
        self.max_depth = self.settings.MAX_DEPTH

    def iter_file_entries(self, root: Path, apply_exclude: bool = True) -> Iterable[Tuple[Path, os.stat_result, bool]]:
        follow_symlinks = getattr(self.cfg.settings, "FOLLOW_SYMLINKS", False)
        yield from self._scan_recursive(root, root, depth=0, follow_symlinks=follow_symlinks, apply_exclude=apply_exclude, visited=set())

    def _scan_recursive(self, root: Path, current_dir: Path, depth: int, follow_symlinks: bool, apply_exclude: bool, visited: set) -> Iterable[Tuple[Path, os.stat_result, bool]]:
        if depth > self.max_depth:
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

        exclude_dirs = set(getattr(self.cfg, "exclude_dirs", []))
        exclude_globs = list(getattr(self.cfg, "exclude_globs", []))
        gitignore_lines = list(getattr(self.cfg, "gitignore_lines", []))
        from sari.core.utils.gitignore import GitignoreMatcher
        gitignore = GitignoreMatcher(gitignore_lines) if gitignore_lines else None
        include_ext = {e.lower() for e in getattr(self.cfg, "include_ext", [])}
        include_files = set(getattr(self.cfg, "include_files", []))
        include_all = not include_ext and not include_files

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
                    if d_name in exclude_dirs: continue
                    if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(d_name, pat) for pat in exclude_dirs):
                        continue
                    if gitignore and gitignore.is_ignored(rel.replace(os.sep, "/"), is_dir=True):
                        continue
                
                yield from self._scan_recursive(root, p, depth + 1, follow_symlinks, apply_exclude, visited)
            
            elif entry.is_file(follow_symlinks=follow_symlinks):
                # File processing
                fn = entry.name
                excluded = any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(fn, pat) for pat in exclude_globs)
                if not excluded and gitignore:
                    rel_posix = rel.replace(os.sep, "/")
                    if gitignore.is_ignored(rel_posix, is_dir=False):
                        excluded = True
                if not excluded and exclude_dirs:
                    rel_parts = rel.split(os.sep)
                    for part in rel_parts:
                        if part in exclude_dirs or any(fnmatch.fnmatch(part, pat) for pat in exclude_dirs):
                            excluded = True
                            break
                
                try: st = entry.stat(follow_symlinks=follow_symlinks)
                except: continue

                # Include filter
                if not include_all:
                    rel_posix = rel.replace(os.sep, "/")
                    ext = p.suffix.lower()
                    included = False
                    if include_files:
                        for pattern in include_files:
                            if fnmatch.fnmatch(fn, pattern) or fnmatch.fnmatch(rel_posix, pattern):
                                included = True
                                break
                    if not included and include_ext and ext in include_ext:
                        included = True
                    if not included:
                        continue

                if apply_exclude and excluded: continue
                yield p, st, excluded
