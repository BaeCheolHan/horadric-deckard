import re
import time
import fnmatch
from pathlib import Path
from typing import List, Optional, Any

def glob_to_like(pattern: str) -> str:
    """Convert glob-style pattern to SQL LIKE pattern for 1st-pass filtering."""
    if not pattern:
        return "%"

    # Better glob-to-like conversion
    res = pattern.replace("**", "%").replace("*", "%").replace("?", "_")

    if not ("%" in res or "_" in res):
        res = f"%{res}%" # Contains if no wildcards

    # Ensure it starts/ends correctly for directory patterns
    if pattern.endswith("/**"):
        res = res.rstrip("%") + "%"

    while "%%" in res:
        res = res.replace("%%", "%")
    return res

def get_file_extension(path: str) -> str:
    ext = Path(path).suffix
    return ext[1:].lower() if ext else ""

def calculate_recency_score(mtime: int, base_score: float) -> float:
    now = time.time()
    age_days = (now - mtime) / 86400
    if age_days < 1:
        boost = 1.5
    elif age_days < 7:
        boost = 1.3
    elif age_days < 30:
        boost = 1.1
    else:
        boost = 1.0

    # Ensure boost works even if base_score is 0 (bias added)
    return (base_score + 0.1) * boost

def extract_terms(q: str) -> List[str]:
    # Use regex to extract quoted phrases or space-separated words
    raw = re.findall(r'"([^"]*)"|\'([^\']*)\'|(\S+)', q or "")
    out: List[str] = []
    for group in raw:
        # group is a tuple of (double_quoted, single_quoted, bare_word)
        t = group[0] or group[1] or group[2]
        t = t.strip()
        if not t or t in {"AND", "OR", "NOT"}:
            continue
        if ":" in t and len(t.split(":", 1)[0]) <= 10:
            t = t.split(":", 1)[1]
        t = t.strip()
        if t:
            out.append(t)
    return out

def count_matches(content: str, query: str, use_regex: bool, case_sensitive: bool) -> int:
    if not query: return 0
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return len(re.findall(query, content, flags))
        except re.error:
            return 0
    else:
        if case_sensitive:
            return content.count(query)
        # Use regex for case-insensitive count to better handle unicode
        try:
            return len(re.findall(re.escape(query), content, re.IGNORECASE))
        except Exception:
            # Fallback to simple count if regex fails for any reason
            return content.lower().count(query.lower())

def snippet_around(content: str, terms: List[str], max_lines: int,
                    highlight: bool = True) -> str:
    if max_lines <= 0:
        return ""
    lines = content.splitlines()
    if not lines:
        return ""

    lower_lines = [l.lower() for l in lines]
    lower_terms = [t.lower() for t in terms if t.strip()]

    if not lower_terms:
        return "\n".join(f"L{i+1}: {ln}" for i, ln in enumerate(lines[:max_lines]))

    # Score per line
    # +1 per match, +5 if definition (def/class) AND match
    line_scores = [0] * len(lines)
    def_pattern = re.compile(r"\b(class|def|function|struct|interface|type)\s+", re.IGNORECASE)

    has_any_match = False
    for i, line_lower in enumerate(lower_lines):
        score = 0
        for t in lower_terms:
            if t in line_lower:
                score += 1

        if score > 0:
            has_any_match = True
            if def_pattern.search(line_lower):
                score += 5

        line_scores[i] = score

    if not has_any_match:
         return "\n".join(f"L{i+1}: {ln}" for i, ln in enumerate(lines[:max_lines]))

    # Find best window (Sliding Window)
    window_size = min(len(lines), max_lines)
    current_score = sum(line_scores[:window_size])
    best_window_score = current_score
    best_start = 0

    for i in range(1, len(lines) - window_size + 1):
        current_score = current_score - line_scores[i-1] + line_scores[i + window_size - 1]
        if current_score > best_window_score:
            best_window_score = current_score
            best_start = i

    # Extract window
    start_idx = best_start
    end_idx = start_idx + window_size

    out_lines = []
    highlight_patterns = [re.compile(re.escape(t), re.IGNORECASE) for t in terms if t.strip()]

    for i in range(start_idx, end_idx):
        line = lines[i]
        if highlight:
            for pat in highlight_patterns:
                # Use backreference to preserve case
                line = pat.sub(r">>>\g<0><<<", line)

        out_lines.append(f"L{i+1}: {line}")

    return "\n".join(out_lines)