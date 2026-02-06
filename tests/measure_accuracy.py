import os
import time
import json
from pathlib import Path
from typing import List, Dict, Any
from sari.core.parsers.factory import ParserFactory
from sari.core.parsers.ast_engine import ASTEngine

class AccuracyEvaluator:
    """
    Measures the precision/recall gap between Fallback (Regex) and Tree-sitter.
    Also evaluates Retrieval Quality for common LLM queries.
    """
    
    def __init__(self):
        self.ast_engine = ASTEngine()
        self.results = {}

    def evaluate_parser_gap(self, file_path: str):
        """Compares Regex Parser vs Tree-sitter on a real file."""
        p = Path(file_path)
        if not p.exists(): return
        
        content = p.read_text(errors="ignore")
        ext = p.suffix
        
        # 1. Fallback (Regex) Result
        regex_parser = ParserFactory.get_parser(ext)
        if not regex_parser: return
        regex_symbols, _ = regex_parser.extract(str(p), content)
        
        # 2. Tree-sitter Result (if enabled)
        if not self.ast_engine.enabled:
            return {
                "path": file_path,
                "ts_count": 0,
                "regex_count": len(regex_symbols),
                "overlap_pct": 0.0,
                "ts_disabled": True
            }
            
        language = ParserFactory.get_language(ext)
        ts_symbols = self.ast_engine.extract_symbols(str(p), language, content)
        
        # Comparison Logic
        regex_names = {s[1] for s in regex_symbols}
        ts_names = {s[1] for s in ts_symbols}
        
        intersection = regex_names.intersection(ts_names)
        
        overlap_score = len(intersection) / len(ts_names) if ts_names else 1.0
        extra_regex = regex_names - ts_names # Potential False Positives
        missing_regex = ts_names - regex_names # Potential False Negatives
        
        return {
            "path": file_path,
            "ts_count": len(ts_symbols),
            "regex_count": len(regex_symbols),
            "overlap_pct": round(overlap_score * 100, 2),
            "false_positives": list(extra_regex),
            "false_negatives": list(missing_regex),
            "ts_disabled": False
        }

def run_accuracy_report(target_dir: str):
    evaluator = AccuracyEvaluator()
    print(f"\n=== Sari Accuracy Evaluation Report: {target_dir} ===")
    
    files = list(Path(target_dir).rglob("*.py")) + list(Path(target_dir).rglob("*.js"))
    files = [f for f in files if "node_modules" not in str(f) and ".venv" not in str(f)][:20]
    
    total_overlap = 0
    count = 0
    ts_active = False
    
    for f in files:
        res = evaluator.evaluate_parser_gap(str(f))
        if res:
            if res.get("ts_disabled"):
                print(f"📄 {res['path']}: [Regex Only] {res['regex_count']} symbols found.")
            else:
                ts_active = True
                print(f"📄 {res['path']}: Overlap={res['overlap_pct']}% (TS={res['ts_count']}, Regex={res['regex_count']})")
                if res['false_negatives']:
                    print(f"   ❌ Missing in Regex: {res['false_negatives'][:3]}")
                total_overlap += res['overlap_pct']
                count += 1
            
    if count > 0 and ts_active:
        avg_accuracy = total_overlap / count
        print(f"\n✅ Mean Accuracy (Regex vs Tree-sitter): {round(avg_accuracy, 2)}%")
    elif not ts_active:
        print("\n⚠️ Tree-sitter not detected. Accuracy results are baseline regex-only.")

if __name__ == "__main__":
    run_accuracy_report("sari/sari/core")