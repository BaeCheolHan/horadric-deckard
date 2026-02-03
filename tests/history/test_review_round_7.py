
import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from mcp.telemetry import TelemetryLogger
from tests.telemetry_helpers import read_log_with_retry

class TestReviewRound7:
    """Round 7: Telemetry & Logging."""

    @pytest.fixture
    def log_dir(self, tmp_path):
        d = tmp_path / "logs"
        d.mkdir()
        return d

    def test_logger_initialization(self, log_dir):
        """Test 1: Logger creates file on init (actually on first write)."""
        logger = TelemetryLogger(log_dir) # Pass Path object
        logger.log_info("test")
        logger.stop()
        
        files = list(log_dir.glob("*.log"))
        assert len(files) >= 1
        assert files[0].name == "deckard.log"

    def test_telemetry_format(self, log_dir):
        """Test 2: log_telemetry format."""
        logger = TelemetryLogger(log_dir)
        logger.log_telemetry("tool=search query='foo' latency=10ms")
        logger.stop()
        
        content = read_log_with_retry(log_dir)
        assert "tool=search" in content
        assert "query='foo'" in content

    def test_append_behavior(self, log_dir):
        """Test 3: Logger appends to existing file."""
        logger = TelemetryLogger(log_dir)
        logger.log_info("First")
        logger.log_info("Second")
        logger.stop()
        
        content = read_log_with_retry(log_dir)
        lines = content.strip().splitlines()
        assert len(lines) >= 2
        assert "First" in lines[-2]
        assert "Second" in lines[-1]

    def test_error_logging(self, log_dir):
        """Test 4: Error logging includes ERROR level."""
        logger = TelemetryLogger(log_dir)
        logger.log_error("Something bad happened")
        logger.stop()
        
        content = read_log_with_retry(log_dir)
        assert "[ERROR]" in content
        assert "Something bad happened" in content
        
    def test_telemetry_timestamp(self, log_dir):
        """Test 5: Logs contain timestamps."""
        logger = TelemetryLogger(log_dir)
        logger.log_info("Time check")
        logger.stop()
        
        content = read_log_with_retry(log_dir)
        # [202...-..-..T..:..:..]
        import re
        assert re.search(r"\[\d{4}-\d{2}-\d{2}", content)
