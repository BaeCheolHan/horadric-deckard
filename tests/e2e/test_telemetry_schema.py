
import pytest
import re
from pathlib import Path
from mcp.telemetry import TelemetryLogger
from tests.telemetry_helpers import read_log_with_retry

class TestShieldTelemetrySchema:
    """
    Round 20: Telemetry Schema & Security Shield.
    Ensures logs are safe and parseable.
    """

    @pytest.fixture
    def log_dir(self, tmp_path):
        d = tmp_path / "logs"
        d.mkdir(exist_ok=True)
        return d

    def test_log_format_timestamp(self, log_dir):
        """
        Shield 1: Logs MUST have ISO timestamp.
        """
        logger = TelemetryLogger(log_dir)
        logger.log_info("Consistency Check")
        logger.stop()
        
        content = read_log_with_retry(log_dir)
        # [202X-XX-XXTXX:XX:XX...
        match = re.search(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", content)
        assert match, "Timestamp missing or malformed"

    def test_telemetry_kv_structure(self, log_dir):
        """
        Shield 2: Telemetry calls produce parseable KV?
        Caller responsibility: caller formats string.
        Logger responsibility: write it.
        We verify logger writes exactly what passed (plus time).
        """
        logger = TelemetryLogger(log_dir)
        logger.log_telemetry("tool=search latency=100")
        logger.stop()
        
        content = read_log_with_retry(log_dir)
        assert "tool=search latency=100" in content

    def test_telemetry_redaction_safety(self, log_dir):
        """
        Shield 3: Telemetry Logger MUST redact secrets.
        If a tool passes a query containing a key, it shouldn't end up in logs.
        """
        logger = TelemetryLogger(log_dir)
        secret = "OPENAI_API_KEY=sk-111111111111111111111111111111111111111111111111"
        logger.log_telemetry(f"query='{secret}'")
        logger.stop()
        
        content = read_log_with_retry(log_dir)
        
        # If this fails, we have a security leak in logging.
        # "Product Shield" methodology demands we fix it.
        assert "sk-11111" not in content, "Secret leaked in logs!"
        
    def test_error_log_structure(self, log_dir):
        """
        Shield 4: Error logs MUST have [ERROR] tag.
        """
        logger = TelemetryLogger(log_dir)
        logger.log_error("Fail")
        logger.stop()
        content = read_log_with_retry(log_dir)
        assert "[ERROR] Fail" in content

    def test_file_permission_safety(self, log_dir):
        """
        Shield 5: If log dir is unwritable, logger should fallback/silent, not crash app.
        """
        # Make dir read-only
        # (Skip on some environments if root, but generally works)
        import os
        os.chmod(log_dir, 0o500) # Read/Execute, No Write
        
        try:
            logger = TelemetryLogger(log_dir)
            logger.log_info("Should not crash")
        except Exception as e:
            pytest.fail(f"Logger crashed on permission error: {e}")
        finally:
            os.chmod(log_dir, 0o700) # Restore
