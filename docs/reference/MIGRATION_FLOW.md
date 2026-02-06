# Migration Flow

## Phase 1: Schema Migration
- Add `roots` table
- Add `root_id` columns to `files`, `symbols`, `symbol_relations`, `snippets`
- Add indexes on `root_id`, `repo`, `mtime`
- No backfill yet (leave null/empty)
- Add embedding staleness fields (`content_hash`, `status`, `updated_ts`)
 - If schema version mismatch, wipe and rebuild

## Phase 2: Reindex (Full)
- Stop watchers
- Clear existing embedded index
- Rebuild global index from DB
- Populate `root_id` for all documents
- Initialize embedding staleness state

## Phase 3: Cutover
- Enable `root_id` query filtering at engine level
- Remove legacy post-filtering
- Validate search results for multiple roots
- Enable read-priority write yielding

## Phase 4: Cleanup
- Remove legacy roots_hash index directories
- Remove deprecated config keys
- Re-enable watchers
- Add `.sariignore` and `.sariroot` support verification

## Validation Checklist
- Confirm `roots` table populated
- Confirm `root_id` present on `files`, `symbols`, `relations`, `snippets`
- Confirm engine index built at global path
- Confirm multi-root queries return correct results
- Confirm indexing resumes without backlog
- Confirm embedding staleness flags work
- Confirm read-priority writes prevent search lockups
