import json
import os
import time
import pytest
import shutil
import urllib.parse
from pathlib import Path
from sari.core.workspace import WorkspaceManager
from sari.core.server_registry import ServerRegistry
from sari.mcp.workspace_registry import Registry
import contextlib
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

class TestNestedWorkspaces:
    
    @pytest.fixture
    def nested_env(self, tmp_path):
        # /tmp/parent
        # /tmp/parent/child
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / ".sari").mkdir()
        (parent / "file_at_parent.py").write_text("parent")
        
        child = parent / "child"
        child.mkdir()
        (child / ".sari").mkdir()
        (child / "file_at_child.py").write_text("child")
        
        env = os.environ.copy()
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "nested_registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        # Force JSON format for easy parsing in tests
        env["SARI_FORMAT"] = "json"
        return str(parent), str(child), env

    def test_overlapping_roots_detection(self, nested_env):
        parent_path, child_path, env = nested_env
        
        # 1. Initialize both workspaces in registry
        import sari.core.server_registry as sr
        
        reg_file = Path(env["SARI_REGISTRY_FILE"])
        
        with patch.object(sr, "get_registry_path", return_value=reg_file):
            registry = sr.ServerRegistry()
            # Register both as active workspaces
            registry.set_workspace(parent_path, "boot-1")
            registry.set_workspace(child_path, "boot-1")
            
            # 2. Run Doctor for the parent workspace
            from sari.mcp.tools.doctor import execute_doctor
            
            with patch.dict("os.environ", env):
                import sari.mcp.tools.doctor as dr_mod
                with patch.object(dr_mod, "get_registry_path", return_value=reg_file):
                    with patch("sari.core.workspace.WorkspaceManager.resolve_workspace_root", return_value=parent_path):
                        res = execute_doctor({})
                        # If SARI_FORMAT is json, execute_doctor returns json text in content
                        text = res["content"][0]["text"]
                        data = json.loads(text)
                        
                        overlap_res = next(r for r in data["results"] if r["name"] == "Workspace Overlap")
                        assert not overlap_res["passed"]
                        assert "Nesting detected" in overlap_res["error"]
                        
                        rec = next(r for r in data["recommendations"] if r["name"] == "Workspace Overlap")
                        assert "Remove nested workspaces" in rec["action"]