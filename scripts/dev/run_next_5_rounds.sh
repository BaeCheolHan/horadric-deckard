#!/bin/bash
set -e

echo "🚀 Starting Rounds 6-10 (25 New Cases)..."
echo "==========================================="

rounds=(
    "tests/e2e/test_round6_paths.py"
    "tests/e2e/test_round7_config_integrity.py"
    "tests/e2e/test_round8_process_edge.py"
    "tests/e2e/test_round9_upgrade.py"
    "tests/e2e/test_round10_integration.py"
)

for i in "${!rounds[@]}"; do
    round_num=$((i+6))
    test_file="${rounds[$i]}"
    echo "🔄 Round $round_num / 10 : $test_file"
    
    if python3 -m pytest "$test_file" -v; then
        echo "✅ Round $round_num PASSED"
    else
        echo "❌ Round $round_num FAILED"
        exit 1
    fi
    echo "--------------------------------------------------------"
done

echo "🎉 All Rounds 6-10 Completed Successfully!"
