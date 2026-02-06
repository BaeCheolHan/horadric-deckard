# Implementation Plan (Ticket-Level)

## Phase 0: Prep
- Confirm configuration file locations
- Confirm profile list and auto-detection rules
- Decide default index worker count (2)

## Phase 1: Config System
### Ticket 1.1: Config path resolution
- Update config path logic to:
  - Global: `~/.config/sari/config.json`
  - Workspace: `<workspace>/.sari/config.json`
- Remove `.codex` references

### Ticket 1.2: Config schema + merge
- Add `include_add`, `exclude_add`, `include_remove`, `exclude_remove`
- Implement merge order:
  1) core profile
  2) auto profiles
  3) global config
  4) workspace config
  5) add lists
  6) remove lists

### Ticket 1.3: Profiles + auto-detect
- Implement profile definitions
- Implement file-based auto-detection rules
- Ensure deterministic merging
### Ticket 1.3b: Auto-detect safe mode
- Default to manual-only mode (auto-detect as recommendations)
- Require explicit opt-in in `.sari/config.json`
### Ticket 1.4: Ignore rules
- Add `.sariignore` support
- Add `.sariroot` boundary marker
- Enforce auto-detect depth limit

## Phase 2: Queue / Watcher / Scheduling
### Ticket 2.1: Priority queue
- Replace or wrap current queue with Aging Priority Queue
- Include per-root weights (WFQ)

### Ticket 2.2: Adaptive debounce
- Add adaptive debounce logic in watcher
- Add token-bucket throttle for event bursts

### Ticket 2.3: Search-first throttling
- When search requests arrive, reduce indexing throughput
### Ticket 2.4: Read-priority DB writes
- Yield DB writes on active search requests
- Split write transactions under read pressure

## Phase 3: Indexing Workers
### Ticket 3.1: Worker pool
- Parallelize parse/document generation
- Default `index_workers=2`
### Ticket 3.1b: Memory budget controls
- Add `SARI_INDEX_MEM_MB` to cap indexing memory
- Add `SARI_INDEX_WORKERS` override
- Adjust batch sizes to fit memory budget

### Ticket 3.2: Batch commit
- Adaptive batch commit thresholds
- Coalesce duplicate writes

### Ticket 3.3: Hash cache + delta indexing
- Cache file content hash
- Skip unchanged files
- Only update delta when possible

### Ticket 3.4: Incremental AST
- Integrate Tree-sitter
- Apply to supported languages
- Fallback to full parse

## Phase 4: DB Schema
### Ticket 4.1: Roots table
- Add `roots` table with root metadata

### Ticket 4.2: root_id columns
- Add `root_id` to:
  - `files`
  - `symbols`
  - `symbol_relations`
  - `snippets`

### Ticket 4.3: Indexes
- Add indexes on `root_id`, `repo`, `mtime`
### Ticket 4.4: Root-aware query helpers
- Introduce a query wrapper that enforces `root_id`
- Disallow raw SQL in cross-root paths
 - Add `apply_root_filter(sql, root_id)` in `sari/sari/core/db/main.py`

## Phase 5: Embedded Engine
### Ticket 5.1: Global index path
- Remove roots_hash-based index path
- Use a single global index directory
### Ticket 5.1b: Shard fallback
- Keep index path policy flexible (global or per-root)

### Ticket 5.2: Query root filter
- Apply `root_id` filter at query time
- Remove post-filtering

### Ticket 5.3: Ranking improvements
- Query rewrite (camel/snake)
- Field weighting (path/name/body)
### Ticket 5.4: Engine memory policy
- Define segment merge policy
- Enforce memory caps for indexing/query

## Phase 6: Migration
### Ticket 6.1: Schema migration
- Add columns + new tables
- Backfill via reindex
### Ticket 6.1b: Wipe-and-rebuild
- If schema version mismatch, delete and rebuild DB

### Ticket 6.2: Rebuild index
- Full rebuild into new global index

### Ticket 6.3: Cleanup
- Remove legacy index paths
- Remove deprecated config keys

## Phase 8: Embeddings Consistency
### Ticket 8.1: Embedding versioning
- Store `content_hash` and `status`
- Mark stale embeddings on file changes
### Ticket 8.2: Search staleness flags
- Expose embedding freshness in search results

## Phase 7: Testing
### Ticket 7.1: Unit
- Config merge
- Queue scheduling fairness
- Hash cache + delta indexing

### Ticket 7.2: Integration
- Watcher -> Indexer -> DB -> Engine
- Multi-root fairness

### Ticket 7.3: Performance
- Initial indexing time
- Burst event handling
- Search latency
