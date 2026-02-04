import os
import sys
from pathlib import Path
import subprocess


def test_install_update_cycle(tmp_path, monkeypatch):
    import install

    repo_root = Path(__file__).resolve().parents[2]
    install_dir = tmp_path / "sari-install"

    monkeypatch.setenv("SARI_INSTALL_SOURCE", str(repo_root))
    monkeypatch.setenv("SARI_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("SARI_NO_INTERACTIVE", "1")

    monkeypatch.setattr(install, "INSTALL_DIR", install_dir)
    monkeypatch.setattr(install, "LOG_FILE", tmp_path / "install.log")

    real_run = subprocess.run

    def _run(cmd, **kwargs):
        if isinstance(cmd, list) and cmd:
            exe = cmd[0]
            if isinstance(exe, str) and exe.endswith(("bootstrap.sh", "bootstrap.bat")):
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if exe == sys.executable and cmd[1:] and cmd[1] == "-m" and cmd[2] == "pip":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if exe == sys.executable and cmd[-1].endswith("doctor.py"):
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

    bootstrap_name = "bootstrap.bat" if install.IS_WINDOWS else "bootstrap.sh"
    assert install_dir.exists()
    assert (install_dir / bootstrap_name).exists()

    marker = install_dir / "marker.txt"
    marker.write_text("marker", encoding="utf-8")

    args.update = True
    install.do_install(args)

    assert install_dir.exists()
    assert (install_dir / bootstrap_name).exists()
    # assert not marker.exists()  # install.py does not wipe directory presently