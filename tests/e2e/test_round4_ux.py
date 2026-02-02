import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import install

class TestRound4UX:
    """Round 4: CLI Flags & Environment Variables"""

    def test_tc1_quiet_mode(self, mock_env, run_install, capsys):
        """TC1: --quiet should produce NO stdout output."""
        install.CONFIG["quiet"] = True # Set global
        run_install({"update": False, "yes": True, "quiet": True}, cwd=mock_env["ws1"])
        
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_tc2_json_output(self, mock_env, run_install, capsys):
        """TC2: --json should produce parsable JSON lines."""
        install.CONFIG["json"] = True
        install.CONFIG["quiet"] = False
        
        run_install({"update": False, "yes": True, "json": True}, cwd=mock_env["ws1"])
        
        captured = capsys.readouterr()
        import json
        for line in captured.out.splitlines():
            if not line: continue
            try:
                data = json.loads(line)
                assert "status" in data
                assert "message" in data
            except json.JSONDecodeError:
                pytest.fail(f"Invalid JSON output: {line}")

    def test_tc3_env_var_override(self, mock_env):
        """TC3: DECKARD_WORKSPACE_ROOT env var should override auto-detection."""
        # We simulate install calling _resolve_workspace_root internally
        with patch.dict("os.environ", {"DECKARD_WORKSPACE_ROOT": str(mock_env["ws2"])}):
            resolved = install._resolve_workspace_root()
            assert resolved == str(mock_env["ws2"])

    def test_tc4_interactive_prompt_skip(self, mock_env):
        """TC4: confirm() should return default if DECKARD_NO_INTERACTIVE is set."""
        with patch.dict("os.environ", {"DECKARD_NO_INTERACTIVE": "1"}):
            assert install.confirm("Test?", default=True) is True
            assert install.confirm("Test?", default=False) is False

    def test_tc5_install_source_override(self, mock_env, run_install):
        """TC5: DECKARD_INSTALL_SOURCE should be used for git clone."""
        custom_source = str(mock_env["home"] / "custom_repo")
        with patch.dict("os.environ", {"DECKARD_INSTALL_SOURCE": custom_source}):
            mock_run = run_install({"update": True, "yes": True}, cwd=mock_env["ws1"])
            
            # Find git clone call in history
            clone_call = None
            for call in mock_run.call_args_list:
                args = call[0][0]
                if "git" in args and "clone" in args:
                    clone_call = args
                    break
            
            assert clone_call is not None, "git clone was not called"
            assert custom_source in clone_call
