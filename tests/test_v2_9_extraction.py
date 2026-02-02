import sys
from pathlib import Path
import json

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import LocalSearchDB
from app.indexer import _extract_symbols

def test_extraction():
    sample_path = str(Path(__file__).parent / "SampleController.java")
    content = Path(sample_path).read_text()
    
    symbols, _ = _extract_symbols(sample_path, content)
    
    print(f"Total symbols found: {len(symbols)}")
    for s in symbols:
        # (path, name, kind, line, end_line, content, parent_name, metadata, docstring)
        print(f"\nSymbol: {s[1]} ({s[2]})")
        print(f"Line: {s[3]} - {s[4]}")
        print(f"Docstring: {s[8].strip()}")
        print(f"Metadata: {s[7]}")
        
        meta = json.loads(s[7])
        if "http_path" in meta:
            print(f"API Path: {meta['http_path']}")

if __name__ == "__main__":
    test_extraction()

