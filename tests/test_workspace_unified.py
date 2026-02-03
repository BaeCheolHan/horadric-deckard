import os
import unittest
import tempfile
import shutil
from pathlib import Path
from app.workspace import WorkspaceManager

class TestWorkspaceUnified(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp_dir)
        # Clear env vars
        self.old_env = {
            "DECKARD_WORKSPACE_ROOT": os.environ.get("DECKARD_WORKSPACE_ROOT"),
            "LOCAL_SEARCH_WORKSPACE_ROOT": os.environ.get("LOCAL_SEARCH_WORKSPACE_ROOT"),
            "DECKARD_CONFIG": os.environ.get("DECKARD_CONFIG"),
            "LOCAL_SEARCH_CONFIG": os.environ.get("LOCAL_SEARCH_CONFIG")
        }
        for k in self.old_env:
            if k in os.environ: del os.environ[k]

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp_dir)
        for k, v in self.old_env.items():
            if v is not None: os.environ[k] = v
            elif k in os.environ: del os.environ[k]

    def test_priority_deckard_env(self):
        """Case 1: DECKARD_WORKSPACE_ROOT priority"""
        os.environ["DECKARD_WORKSPACE_ROOT"] = self.tmp_dir
        os.environ["LOCAL_SEARCH_WORKSPACE_ROOT"] = "/invalid/path"
        self.assertEqual(WorkspaceManager.resolve_workspace_root(), str(Path(self.tmp_dir).absolute()))

    def test_priority_local_search_env(self):
        """Case 2: LOCAL_SEARCH_WORKSPACE_ROOT fallback"""
        os.environ["LOCAL_SEARCH_WORKSPACE_ROOT"] = self.tmp_dir
        self.assertEqual(WorkspaceManager.resolve_workspace_root(), str(Path(self.tmp_dir).absolute()))

    def test_cwd_placeholder(self):
        """Case 3: ${cwd} string replacement"""
        os.environ["DECKARD_WORKSPACE_ROOT"] = "${cwd}"
        self.assertEqual(WorkspaceManager.resolve_workspace_root(), str(Path(os.getcwd()).absolute()))

    def test_file_uri_handling(self):
        """Case 4: file:// URI handling"""
        uri = f"file://{self.tmp_dir}"
        self.assertEqual(WorkspaceManager.resolve_workspace_root(uri), str(Path(self.tmp_dir).absolute()))

    def test_fallback_to_cwd(self):
        """Case 5: fallback to cwd when no roots specified"""
        sub_dir = Path(self.tmp_dir) / "sub"
        sub_dir.mkdir()
        os.chdir(str(sub_dir))
        self.assertEqual(WorkspaceManager.resolve_workspace_root(), str(Path(sub_dir).resolve()))

if __name__ == "__main__":
    unittest.main()
