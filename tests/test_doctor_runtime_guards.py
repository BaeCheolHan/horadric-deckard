from unittest.mock import MagicMock

from sari.mcp.tools.doctor import (
    _check_db_migration_safety,
    _check_storage_switch_guard,
    _check_writer_health,
)


def test_doctor_reports_non_destructive_db_migration_policy():
    res = _check_db_migration_safety()
    assert res["name"] == "DB Migration Safety"
    assert res["passed"] is True


def test_doctor_storage_switch_guard_reports_blocked_state():
    from sari.core.db.storage import GlobalStorageManager

    old_reason = GlobalStorageManager._last_switch_block_reason
    old_ts = GlobalStorageManager._last_switch_block_ts
    try:
        GlobalStorageManager._last_switch_block_reason = "previous writer did not stop cleanly"
        GlobalStorageManager._last_switch_block_ts = 1.0
        res = _check_storage_switch_guard()
        assert res["name"] == "Storage Switch Guard"
        assert res["passed"] is False
        assert "blocked" in res["error"]
    finally:
        GlobalStorageManager._last_switch_block_reason = old_reason
        GlobalStorageManager._last_switch_block_ts = old_ts


def test_doctor_writer_health_without_storage_instance_is_safe():
    from sari.core.db.storage import GlobalStorageManager

    old_instance = GlobalStorageManager._instance
    try:
        GlobalStorageManager._instance = None
        res = _check_writer_health(MagicMock())
        assert res["name"] == "Writer Health"
        assert res["passed"] is True
    finally:
        GlobalStorageManager._instance = old_instance
