import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mcp.tools.doctor as doctor


def test_doctor_basic_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_check_network", lambda: {"name": "Network Check", "passed": True, "error": ""})
    monkeypatch.setattr(doctor, "_check_port", lambda port: {"name": f"Port {port} Availability", "passed": True, "error": ""})
    monkeypatch.setattr(doctor, "_check_daemon", lambda: {"name": "Deckard Daemon", "passed": True, "error": ""})
    monkeypatch.setattr(doctor, "_check_disk_space", lambda ws, gb: {"name": "Disk Space", "passed": True, "error": ""})
    monkeypatch.setattr(doctor, "_check_marker", lambda ws: {"name": "Workspace Marker (.codex-root)", "passed": True, "error": ""})
    monkeypatch.setattr(doctor, "_check_db", lambda ws: [{"name": "DB Existence", "passed": True, "error": ""}])
    monkeypatch.setattr(doctor.WorkspaceManager, "resolve_workspace_root", lambda: str(tmp_path))

    res = doctor.execute_doctor({"include_network": True, "include_port": True})
    payload = json.loads(res["content"][0]["text"])
    assert payload["workspace_root"] == str(tmp_path)
    assert isinstance(payload["results"], list)
    assert any(r["name"] == "DB Existence" for r in payload["results"])


def test_doctor_disable_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.WorkspaceManager, "resolve_workspace_root", lambda: str(tmp_path))
    res = doctor.execute_doctor({
        "include_network": False,
        "include_port": False,
        "include_db": False,
        "include_disk": False,
        "include_daemon": False,
        "include_venv": False,
        "include_marker": False,
    })
    payload = json.loads(res["content"][0]["text"])
    assert payload["results"] == []
