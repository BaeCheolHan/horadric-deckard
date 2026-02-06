# Script Layout

- `bootstrap.sh`: runtime/bootstrap entrypoint used by installer and local startup flow.
- `scripts/verify-gates.sh`: CI/local gate checks.
- `scripts/run_tests_isolated.sh`: run tests in isolated HOME/registry/log environment.
- `scripts/run_edge_tests.sh`: convenience edge-case test runner.
- `scripts/prune_tokenizer_bundles.sh`: keep only current-platform tokenizer wheels.
- `scripts/dev/`: ad-hoc/manual stress rounds for local development.
