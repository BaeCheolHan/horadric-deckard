import sys
from pathlib import Path
import subprocess


def _install_with_source(tmp_path, monkeypatch, source):
    import install

    install_dir = tmp_path / "sari-install"
    repo_root = Path(__file__).resolve().parents[2]

    monkeypatch.setenv("SARI_INSTALL_SOURCE", source)
    monkeypatch.setenv("SARI_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("SARI_NO_INTERACTIVE", "1")

    monkeypatch.setattr(install, "INSTALL_DIR", install_dir)
    monkeypatch.setattr(install, "LOG_FILE", tmp_path / "install.log")

    real_run = subprocess.run

    def _run(cmd, **kwargs):
        if isinstance(cmd, list) and cmd[:2] == ["git", "clone"]:
            raise subprocess.CalledProcessError(1, cmd, "fail", "fail")
        if isinstance(cmd, list) and cmd and cmd[0] == sys.executable and cmd[-1].endswith("doctor.py"):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(install.subprocess, "run", _run)

    install.CONFIG.update({"quiet": True, "json": False, "verbose": False})
    args = install.argparse.Namespace(
        uninstall=False,
        update=False,
        yes=True,
        quiet=True,
        json=False,
        verbose=False,
    )
    install.do_install(args)
    assert install_dir.exists()
    assert (install_dir / ("bootstrap.bat" if install.IS_WINDOWS else "bootstrap.sh")).exists()
    # Ensure we copied from local source when available
    assert (install_dir / "README.md").exists()
    assert (install_dir / "install.py").exists()
    assert (install_dir / "LICENSE").exists()
    assert (install_dir / "sari").exists()
    assert repo_root.exists()


def test_install_local_source_path(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    _install_with_source(tmp_path, monkeypatch, str(repo_root))


def test_install_file_url_source(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    _install_with_source(tmp_path, monkeypatch, f"file://{repo_root}")


def test_install_fallback_when_clone_fails(tmp_path, monkeypatch):
    _install_with_source(tmp_path, monkeypatch, "https://example.invalid/sari.git")
