import unittest
import tempfile
import shutil
from pathlib import Path

from mcp.server import LocalSearchMCPServer
from mcp.telemetry import TelemetryLogger


class TestSearchFirstTelemetry(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_dir = Path(self.tmp_dir) / "logs"
        self.log_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_search_first_warning_logs(self):
        server = LocalSearchMCPServer(self.tmp_dir)
        server._search_first_mode = "warn"
        server.logger = TelemetryLogger(self.log_dir)
        server._search_first_warning({"warnings": []})

        content = (self.log_dir / "deckard.log").read_text()
        self.assertIn("policy=search_first", content)
        self.assertIn("action=warn", content)

    def test_search_first_enforce_logs(self):
        server = LocalSearchMCPServer(self.tmp_dir)
        server._search_first_mode = "enforce"
        server.logger = TelemetryLogger(self.log_dir)
        server._search_first_error()

        content = (self.log_dir / "deckard.log").read_text()
        self.assertIn("policy=search_first", content)
        self.assertIn("action=enforce", content)


if __name__ == "__main__":
    unittest.main()
