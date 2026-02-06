from pathlib import Path
from types import SimpleNamespace

from sari.core.indexer.scanner import Scanner
from sari.core.workspace import WorkspaceManager
from sari.core.settings import settings


def test_find_project_root_ignores_sari_marker(tmp_path):
    repo = tmp_path / "repo"
    child = repo / "sub"
    child.mkdir(parents=True)
    (repo / ".sari").mkdir()
    found = WorkspaceManager.find_project_root(str(child))
    # .sari is config-only; it must not act as a boundary marker.
    assert found == str(child.resolve())


def test_find_project_root_uses_sariroot(tmp_path):
    repo = tmp_path / "repo"
    child = repo / "sub"
    child.mkdir(parents=True)
    (repo / ".sariroot").write_text("", encoding="utf-8")
    found = WorkspaceManager.find_project_root(str(child))
    assert found == str(repo.resolve())


def test_scanner_does_not_skip_sari_dir_without_active_subworkspace(tmp_path):
    root = tmp_path / "root"
    target = root / "project"
    target.mkdir(parents=True)
    (target / ".sari").mkdir()
    f = target / "Main.java"
    f.write_text("class Main {}", encoding="utf-8")

    cfg = SimpleNamespace(
        include_ext=[".java"],
        include_files=[],
        exclude_dirs=[],
        exclude_globs=[],
        gitignore_lines=[],
        settings=SimpleNamespace(FOLLOW_SYMLINKS=False, MAX_DEPTH=10),
    )
    scanner = Scanner(cfg, active_workspaces=[])
    paths = [str(p) for p, _st, _excluded in scanner.iter_file_entries(root)]
    assert any(p.endswith("Main.java") for p in paths)


def test_manual_only_default_is_false():
    assert settings.MANUAL_ONLY is False
