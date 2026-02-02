#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="$(mktemp -d -t deckard-test-XXXXXX)"

cleanup() {
  rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

DAEMON_PORT="$(
  python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"

export HOME="${TMP_ROOT}/home"
export DECKARD_REGISTRY_FILE="${TMP_ROOT}/registry.json"
export DECKARD_LOG_DIR="${TMP_ROOT}/logs"
export DECKARD_DAEMON_PORT="${DAEMON_PORT}"

mkdir -p "$HOME" "$DECKARD_LOG_DIR"

cd "$ROOT_DIR"
python3 -m pytest "$@"
