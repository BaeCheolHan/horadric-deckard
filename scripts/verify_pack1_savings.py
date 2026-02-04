#!/usr/bin/env python3
import sys
import os
import json
import time
from pathlib import Path

# Add project root to sys.path
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)

from sari.core.db import LocalSearchDB
from sari.mcp.tools.list_files import execute_list_files
from sari.mcp.tools.search import execute_search
from sari.mcp.telemetry import TelemetryLogger

class MockLogger:
    def log_telemetry(self, msg):
        pass

def run_test():
    # Setup DB (use existing test db or create temp?)
    # Using a temp DB with some dummy data for consistency
    import tempfile
    import shutil

    tmp_dir = tempfile.mkdtemp()
    db_path = str(Path(tmp_dir) / "test.db")
    db = LocalSearchDB(db_path)
    logger = MockLogger()

    # Insert dummy data (enough to see difference)
    files = []
    ts = int(time.time())
    for i in range(100):
        files.append((f"src/module_{i}/main.py", "repo1", 0, 0, f"class User{i}: pass\n def login(): pass", ts))

    db.upsert_files(files)

    # Define test cases
    cases = [
        ("list_files", execute_list_files, {"repo": "repo1", "limit": 50}),
        ("search", execute_search, {"query": "User", "limit": 20})
    ]

    print(f"{'Tool':<15} | {'Format':<6} | {'Bytes':<8} | {'Savings':<8}")
    print("-" * 50)

    for tool_name, tool_func, args in cases:
        # JSON Run
        os.environ["SARI_FORMAT"] = "json"
        res_json = tool_func(args, db, logger)
        json_bytes = len(res_json["content"][0]["text"].encode("utf-8"))

        # PACK1 Run
        os.environ["SARI_FORMAT"] = "pack"
        res_pack = tool_func(args, db, logger)
        pack_bytes = len(res_pack["content"][0]["text"].encode("utf-8"))

        savings = (json_bytes - pack_bytes) / json_bytes * 100

        print(f"{tool_name:<15} | JSON   | {json_bytes:<8} | -")
        print(f"{tool_name:<15} | PACK1  | {pack_bytes:<8} | {savings:.1f}%")
        print("-" * 50)

    # Cleanup
    db.close()
    shutil.rmtree(tmp_dir)

if __name__ == "__main__":
    run_test()
