#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[gate] running critical gate tests..."
python3 -m pytest -q -m gate

echo "[gate] running core smoke suite..."
python3 -m pytest -q \
  tests/test_core_main.py \
  tests/test_engines.py \
  tests/test_server.py \
  tests/test_search_engine_mapping.py

echo "[gate] all checks passed."
