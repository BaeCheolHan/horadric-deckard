#!/bin/bash
set -e

echo "🚀 Starting Rounds 11-15 (25 Expert Test Cases)..."
echo "=================================================="

rounds=(
    "tests/e2e/test_round11_config_gen.py"
    "tests/e2e/test_round12_doctor_logic.py"
    "tests/e2e/test_round13_registry.py"
    "tests/e2e/test_round14_uninstall_deep.py"
    "tests/e2e/test_round15_chaos.py"
)

for i in "${!rounds[@]}"; do
    round_num=$((i+11))
    test_file="${rounds[$i]}"
    echo "🔄 Round $round_num / 15 : $test_file"
    
    if python3 -m pytest "$test_file" -v; then
        echo "✅ Round $round_num PASSED"
    else
        echo "❌ Round $round_num FAILED"
        exit 1
    fi
    echo "--------------------------------------------------------"
done

echo "🎉 All Rounds 11-15 Completed Successfully! (Total 70+ Cases Verified)"
