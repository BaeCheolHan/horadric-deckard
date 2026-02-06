# Risks & Tradeoffs

## 1. Complexity vs Maintainability
- Adding advanced scheduling and incremental parsing increases system complexity.
- Mitigation: isolate algorithms in dedicated modules and keep interfaces stable.

## 2. Incremental AST Accuracy
- Incremental parsing can diverge from full parse in edge cases.
- Mitigation: fallback to full parse on parser errors or suspicious diffs.

## 3. Resource Constraints (Laptop)
- Parallel workers increase CPU and memory usage.
- Mitigation: default to 2 workers, adaptive throttling during system load.

## 4. Index Consistency
- Using delta indexing requires strict correctness of change detection.
- Mitigation: content hash cache + periodic revalidation sweep.

## 5. Migration Risk
- Schema changes and engine rebuild can cause downtime.
- Mitigation: staged migration with full reindex in a controlled window.

## 6. Query Quality vs Latency
- Query rewrite and field weighting can improve results but add small latency.
- Mitigation: lightweight rewrite rules and cached compiled queries.

## 7. Cross-Workspace Fairness
- WFQ prevents starvation but can delay large single-workspace jobs.
- Mitigation: allow per-workspace weight tuning.

## 8. SQLite Read/Write Contention
- Single-writer SQLite can block read-heavy search during large commits.
- Mitigation: read-priority write yielding and smaller batch transactions under read pressure.

## 13. Root Filter Omissions
- Missing `root_id` filter can leak cross-workspace data.
- Mitigation: enforce `apply_root_filter(sql, root_id)` in DB helper layer.

## 9. Global Index Memory Pressure
- Single global Tantivy index can cause noisy-neighbor effects.
- Mitigation: segment merge policy + memory caps + root-weighted query filters.

## 10. Auto-Detect Traps
- Mis-detection from deep dependencies (node_modules, vendor).
- Mitigation: `.sariignore`, project boundary markers, and depth limits.
 - Optional: manual-only mode (auto-detect as recommendations only).

## 11. Embedding Staleness
- Embedding generation is slower than text indexing.
- Mitigation: version embeddings by content hash and surface staleness flags.

## 12. LLM Context Explosion
- Graph/artifact payloads can exceed token budgets.
- Mitigation: token budget enforcement + summary-first responses.
