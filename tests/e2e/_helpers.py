from __future__ import annotations

from pathlib import Path


def db_files_count(db_path: Path) -> int:
    import sqlite3
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()
