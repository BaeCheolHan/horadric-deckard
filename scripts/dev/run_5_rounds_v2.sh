#!/bin/bash
set -e

echo "🚀 Starting 5-Round Advanced Installation Stress Test..."
echo "========================================================"

rounds=(
    "tests/e2e/test_round1_edge.py"
    "tests/e2e/test_round2_logic.py"
    "tests/e2e/test_round3_process.py"
    "tests/e2e/test_round4_ux.py"
    "tests/e2e/test_round5_full_system.py"
)

for i in "${!rounds[@]}"; do
    round_num=$((i+1))
    test_file="${rounds[$i]}"
    echo "🔄 Round $round_num / 5 : $test_file"
    
    if python3 -m pytest "$test_file" -v; then
        echo "✅ Round $round_num PASSED"
    else
        echo "❌ Round $round_num FAILED"
        exit 1
    fi
    echo "--------------------------------------------------------"
done

echo "🎉 All 5 Rounds (20+ Cases) Completed Successfully!"
