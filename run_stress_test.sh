#!/bin/bash
set -e

# Setup PYTHONPATH for install.py
export PYTHONPATH=$PYTHONPATH:$(pwd)

echo "🚀 Starting 5-Round Installation Stress Test..."
echo "============================================="

for i in {1..5}
do
    echo "🔄 Round $i / 5"
    if python3 -m pytest tests/e2e/test_install_cycles.py -v; then
        echo "✅ Round $i PASSED"
    else
        echo "❌ Round $i FAILED"
        exit 1
    fi
    echo "---------------------------------------------"
done

echo "🎉 All 5 Rounds Completed Successfully!"
