#!/bin/bash
set -e

# Setup PYTHONPATH for install.py
export PYTHONPATH=$PYTHONPATH:$(pwd)/sari

echo "🚀 Starting 5-Round Installation Stress Test..."
echo "============================================="

# Tokenizer bundle check (warning only)
if [ -d "app/engine_tokenizer_data" ]; then
  count=$(ls app/engine_tokenizer_data/lindera_python_ipadic-*.whl 2>/dev/null | wc -l | tr -d ' ')
  if [ "$count" = "0" ]; then
    echo "⚠️  tokenizer bundle missing: app/engine_tokenizer_data"
  fi
fi

for i in {1..5}
do
    echo "🔄 Round $i / 5"
    if python3 -m pytest sari/tests/e2e/test_install_cycles.py -v; then
        echo "✅ Round $i PASSED"
    else
        echo "❌ Round $i FAILED"
        exit 1
    fi
    echo "---------------------------------------------"
done

echo "🎉 All 5 Rounds Completed Successfully!"
