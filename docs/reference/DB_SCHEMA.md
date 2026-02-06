# Database Schema (Redesign)

## Goals
- Unified DB for multiple workspaces
- Explicit `root_id` tenancy on all core tables
- Efficient filtering, deletion, and maintenance
- Extendable schema without frequent migrations

## Tables

### schema_version
Tracks schema migrations.

Columns:
- `version` INTEGER PRIMARY KEY
- `applied_ts` INTEGER NOT NULL

---

### roots
Tracks workspaces and their metadata.

Columns:
- `root_id` TEXT PRIMARY KEY (hash of normalized path)
- `root_path` TEXT NOT NULL (original path)
- `real_path` TEXT NOT NULL (resolved path)
- `label` TEXT DEFAULT ''
- `state` TEXT DEFAULT 'active'  -- active|deleted|paused
- `config_json` TEXT DEFAULT '{}'  -- cached config snapshot
- `created_ts` INTEGER NOT NULL
- `updated_ts` INTEGER NOT NULL

Indexes:
- `idx_roots_state` (state)
- `idx_roots_real_path` (real_path)

---

### files
Stores indexed file content and metadata.

Columns:
- `path` TEXT PRIMARY KEY (root_id/rel)
- `root_id` TEXT NOT NULL
- `repo` TEXT NOT NULL
- `mtime` INTEGER NOT NULL
- `size` INTEGER NOT NULL
- `content` BLOB NOT NULL
- `content_hash` TEXT DEFAULT ''
- `fts_content` TEXT DEFAULT ''
- `last_seen` INTEGER DEFAULT 0
- `deleted_ts` INTEGER DEFAULT 0
- `parse_status` TEXT NOT NULL DEFAULT 'none'
- `parse_reason` TEXT NOT NULL DEFAULT 'none'
- `ast_status` TEXT NOT NULL DEFAULT 'none'
- `ast_reason` TEXT NOT NULL DEFAULT 'none'
- `is_binary` INTEGER NOT NULL DEFAULT 0
- `is_minified` INTEGER NOT NULL DEFAULT 0
- `sampled` INTEGER NOT NULL DEFAULT 0
- `content_bytes` INTEGER NOT NULL DEFAULT 0
- `metadata_json` TEXT DEFAULT '{}'

Indexes:
- `idx_files_root_id` (root_id)
- `idx_files_repo` (repo)
- `idx_files_mtime` (mtime DESC)
- `idx_files_last_seen` (last_seen)
- `idx_files_deleted_ts` (deleted_ts)
- `idx_files_content_hash` (content_hash)

---

### symbols
Symbol index extracted from files.

Columns:
- `path` TEXT NOT NULL
- `root_id` TEXT NOT NULL
- `name` TEXT NOT NULL
- `kind` TEXT NOT NULL
- `line` INTEGER NOT NULL
- `end_line` INTEGER NOT NULL
- `content` TEXT NOT NULL
- `parent_name` TEXT DEFAULT ''
- `metadata` TEXT DEFAULT '{}'
- `docstring` TEXT DEFAULT ''
- `qualname` TEXT DEFAULT ''
- `symbol_id` TEXT DEFAULT ''

Indexes:
- `idx_symbols_root_id` (root_id)
- `idx_symbols_path` (path)
- `idx_symbols_name` (name)

---

### symbol_relations
Symbol call/usage relations.

Columns:
- `from_path` TEXT NOT NULL
- `from_root_id` TEXT NOT NULL
- `from_symbol` TEXT NOT NULL
- `from_symbol_id` TEXT DEFAULT ''
- `to_path` TEXT NOT NULL
- `to_root_id` TEXT NOT NULL
- `to_symbol` TEXT NOT NULL
- `to_symbol_id` TEXT DEFAULT ''
- `rel_type` TEXT NOT NULL
- `line` INTEGER NOT NULL
- `metadata_json` TEXT DEFAULT '{}'

Indexes:
- `idx_rel_from_root` (from_root_id)
- `idx_rel_to_root` (to_root_id)
- `idx_rel_from_path` (from_path)
- `idx_rel_to_path` (to_path)

---

### repo_meta
Repository metadata.

Columns:
- `repo_name` TEXT PRIMARY KEY
- `tags` TEXT
- `domain` TEXT
- `description` TEXT
- `priority` INTEGER DEFAULT 0

Indexes:
- `idx_repo_meta_priority` (priority)

---

### snippets
Saved code snippets.

Columns:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `tag` TEXT NOT NULL
- `path` TEXT NOT NULL
- `root_id` TEXT NOT NULL
- `start_line` INTEGER NOT NULL
- `end_line` INTEGER NOT NULL
- `content` TEXT NOT NULL
- `content_hash` TEXT NOT NULL
- `anchor_before` TEXT DEFAULT ''
- `anchor_after` TEXT DEFAULT ''
- `repo` TEXT DEFAULT ''
- `note` TEXT DEFAULT ''
- `commit_hash` TEXT DEFAULT ''
- `created_ts` INTEGER NOT NULL
- `updated_ts` INTEGER NOT NULL
- `metadata_json` TEXT DEFAULT '{}'

Indexes:
- `idx_snippets_root_id` (root_id)
- `idx_snippets_tag` (tag)

---

### contexts
Knowledge store.

Columns:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `topic` TEXT NOT NULL UNIQUE
- `content` TEXT NOT NULL
- `tags_json` TEXT DEFAULT '[]'
- `related_files_json` TEXT DEFAULT '[]'
- `source` TEXT DEFAULT ''
- `valid_from` INTEGER DEFAULT 0
- `valid_until` INTEGER DEFAULT 0
- `deprecated` INTEGER DEFAULT 0
- `created_ts` INTEGER NOT NULL
- `updated_ts` INTEGER NOT NULL

---

### failed_tasks
Dead letter queue for indexing.

Columns:
- `path` TEXT PRIMARY KEY
- `root_id` TEXT NOT NULL
- `attempts` INTEGER NOT NULL
- `error` TEXT NOT NULL
- `ts` INTEGER NOT NULL
- `next_retry` INTEGER NOT NULL
- `metadata_json` TEXT DEFAULT '{}'

Indexes:
- `idx_failed_root_id` (root_id)

---

### engine_state
Tracks embedded engine metadata.

Columns:
- `key` TEXT PRIMARY KEY
- `value` TEXT NOT NULL
- `updated_ts` INTEGER NOT NULL

Suggested keys:
- `engine_version`
- `index_version`
- `last_commit_ts`
- `doc_count`

---

### analysis_runs
Tracks analysis executions (codeMRI, etc).

Columns:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `root_id` TEXT NOT NULL
- `type` TEXT NOT NULL  -- e.g., health, complexity, refactor, dependency
- `params_json` TEXT DEFAULT '{}'
- `status` TEXT DEFAULT 'pending'
- `created_ts` INTEGER NOT NULL
- `updated_ts` INTEGER NOT NULL

Indexes:
- `idx_analysis_root_id` (root_id)
- `idx_analysis_type` (type)
- `idx_analysis_status` (status)

---

### artifacts
Stores analysis outputs (reports, metrics, summaries).

Columns:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `root_id` TEXT NOT NULL
- `type` TEXT NOT NULL  -- e.g., metrics, report, scorecard
- `version` TEXT DEFAULT ''
- `payload_json` TEXT NOT NULL
- `created_ts` INTEGER NOT NULL

Indexes:
- `idx_artifacts_root_id` (root_id)
- `idx_artifacts_type` (type)

---

### graphs
Stores structural graphs (call graph, dependency graph).

Columns:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `root_id` TEXT NOT NULL
- `name` TEXT NOT NULL
- `payload_json` TEXT NOT NULL
- `created_ts` INTEGER NOT NULL

Indexes:
- `idx_graphs_root_id` (root_id)

---

### embeddings (optional)
Stores vector embeddings for semantic search.

Columns:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `root_id` TEXT NOT NULL
- `entity_type` TEXT NOT NULL  -- file|symbol|snippet|doc
- `entity_id` TEXT NOT NULL
- `content_hash` TEXT NOT NULL
- `model` TEXT NOT NULL
- `status` TEXT DEFAULT 'ready'  -- ready|stale|failed
- `vector` BLOB NOT NULL
- `created_ts` INTEGER NOT NULL
- `updated_ts` INTEGER NOT NULL

Indexes:
- `idx_embeddings_root_id` (root_id)
- `idx_embeddings_entity` (entity_type, entity_id)

## Notes
- `path` remains unique (`root_id/rel`) to avoid collisions
- `root_id` is always stored explicitly for filtering and cleanup
- `symbol_relations` uses both from/to root for multi-root safety
- On schema version mismatch, wipe and rebuild the DB (no backward compatibility)
