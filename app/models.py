from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class SearchHit:
    """Enhanced search result with metadata."""
    repo: str
    path: str
    score: float
    snippet: str
    # v2.3.1: Added metadata
    mtime: int = 0
    size: int = 0
    match_count: int = 0
    file_type: str = ""
    hit_reason: str = ""  # v2.4.3: Added hit reason
    context_symbol: str = ""  # v2.6.0: Enclosing symbol context
    docstring: str = "" # v2.9.0: Docstring/Javadoc
    metadata: str = "{}" # v2.9.0: Raw metadata JSON


@dataclass
class SearchOptions:
    """Search configuration options (v2.5.1)."""
    query: str = ""
    repo: Optional[str] = None
    limit: int = 20
    offset: int = 0
    snippet_lines: int = 5
    # Filtering
    file_types: List[str] = field(default_factory=list)  # e.g., ["py", "ts"]
    path_pattern: Optional[str] = None  # e.g., "src/**/*.ts"
    exclude_patterns: List[str] = field(default_factory=list)  # e.g., ["node_modules", "build"]
    recency_boost: bool = False
    use_regex: bool = False
    case_sensitive: bool = False
    root_ids: List[str] = field(default_factory=list)
    # Pagination & Performance (v2.5.1)
    total_mode: str = "exact"  # "exact" | "approx"
