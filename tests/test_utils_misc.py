import pytest
import logging
import os
from sari.core.utils.compression import _compress, _decompress
from sari.core.utils.logging import get_logger, setup_global_logging
from sari.core.workspace import WorkspaceManager

def test_compression():
    text = "Hello World" * 100
    compressed = _compress(text)
    assert isinstance(compressed, bytes)
    assert len(compressed) < len(text.encode("utf-8"))
    
    decompressed = _decompress(compressed)
    assert decompressed == text
    
    assert _compress("") == b""
    assert _decompress(b"") == ""
    assert _decompress("already string") == "already string"
    assert _decompress(b"invalid data") == str(b"invalid data")

def test_get_logger(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger("test_logger", log_file=str(log_file))
    
    assert logger.name == "test_logger"
    assert len(logger.handlers) >= 2 # Stream + File
    
    logger.info("Test message")
    assert log_file.exists()
    with open(log_file, "r") as f:
        content = f.read()
        assert "Test message" in content

def test_setup_global_logging():
    # This just calls logging.basicConfig, hard to assert effect without side effects
    # but we can ensure it doesn't crash.
    setup_global_logging()


def test_workspace_normalize_path_never_returns_empty_for_root():
    assert WorkspaceManager.normalize_path("/") == "/"


def test_workspace_normalize_path_empty_falls_back_to_cwd():
    out = WorkspaceManager.normalize_path("")
    assert isinstance(out, str)
    assert out != ""
