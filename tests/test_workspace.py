import json
import os
from pathlib import Path

from app.workspace import WorkspaceManager


def test_resolve_workspace_roots_priority(tmp_path, monkeypatch):
    root_cfg = tmp_path / "cfg"
    root_env = tmp_path / "env"
    root_json = tmp_path / "json"
    root_cfg.mkdir()
    root_env.mkdir()
    root_json.mkdir()

    monkeypatch.setenv("DECKARD_ROOT_1", str(root_env))
    roots_json = json.dumps([str(root_json)])

    roots = WorkspaceManager.resolve_workspace_roots(
        root_uri=None,
        roots_json=roots_json,
        roots_env=os.environ,
        config_roots=[str(root_cfg)],
    )

    assert roots[0].endswith(str(root_cfg).rstrip(os.sep))
    assert any(r.endswith(str(root_env).rstrip(os.sep)) for r in roots)
    assert any(r.endswith(str(root_json).rstrip(os.sep)) for r in roots)


def test_resolve_config_path_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    workspace_root = tmp_path / "ws"
    legacy_dir = workspace_root / ".codex" / "tools" / "deckard" / "config"
    legacy_dir.mkdir(parents=True)
    legacy_path = legacy_dir / "config.json"
    legacy_path.write_text(json.dumps({"roots": ["/tmp"]}), encoding="utf-8")

    cfg_path = WorkspaceManager.resolve_config_path(str(workspace_root))
    cfg_path = Path(cfg_path)
    assert cfg_path.exists()
    assert json.loads(cfg_path.read_text(encoding="utf-8")).get("roots") == ["/tmp"]
    # legacy should be backed up or marked
    assert legacy_path.with_suffix(".json.bak").exists() or (legacy_dir / ".migrated").exists()


def test_resolve_config_path_env_override(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DECKARD_CONFIG", str(cfg_path))
    resolved = WorkspaceManager.resolve_config_path(str(tmp_path))
    assert resolved == str(cfg_path.resolve())


def test_root_id_stable(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    first = WorkspaceManager.root_id(str(root))
    second = WorkspaceManager.root_id(str(root))
    assert first == second


def test_is_path_allowed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    assert WorkspaceManager.is_path_allowed(str(file_path), [str(root)]) is True
    other = tmp_path / "other.txt"
    other.write_text("y", encoding="utf-8")
    assert WorkspaceManager.is_path_allowed(str(other), [str(root)]) is False


def test_resolve_workspace_roots_root_uri_keep_nested(tmp_path, monkeypatch):
    root_a = tmp_path / "a"
    root_b = root_a / "b"
    root_a.mkdir()
    root_b.mkdir()
    monkeypatch.setenv("DECKARD_KEEP_NESTED_ROOTS", "1")
    roots = WorkspaceManager.resolve_workspace_roots(
        root_uri=f"file://{root_b}",
        roots_env=os.environ,
        config_roots=[str(root_a)],
    )
    assert any(r.endswith(str(root_a).rstrip(os.sep)) for r in roots)
    assert any(r.endswith(str(root_b).rstrip(os.sep)) for r in roots)


def test_resolve_workspace_roots_legacy_env(tmp_path, monkeypatch):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    monkeypatch.setenv("DECKARD_WORKSPACE_ROOT", str(root_a))
    monkeypatch.setenv("LOCAL_SEARCH_WORKSPACE_ROOT", str(root_b))
    roots = WorkspaceManager.resolve_workspace_roots(roots_env=os.environ)
    assert roots[0].endswith(str(root_a).rstrip(os.sep))


def test_resolve_workspace_root_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("DECKARD_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("LOCAL_SEARCH_WORKSPACE_ROOT", raising=False)
    root = WorkspaceManager.resolve_workspace_root()
    assert root
