# Sari Architecture (Re-Design)

## Goals
- Local machine (MacBook M3 24GB) target
- Up to 10 workspaces / 50 repos
- Search should feel immediate
- Maintain accuracy and completeness
- Minimal configuration overhead

## Operating Targets
- Index concurrency: 2 (default), 3 max
- Search concurrency: 10-20
- Build/checkout bursts handled gracefully
- Initial indexing (build outputs excluded):
  - 10-20k files / 1-3GB: 3-10 min
  - 50k files / 5-10GB: 10-30 min
  - 100k files / 10-20GB: 30-90 min

## Configuration
### File Locations
- Global: `~/.config/sari/config.json`
- Workspace: `<workspace>/.sari/config.json`

### Merge Model
- Auto-detect profiles + add/remove overrides
- Use union merging with removal lists

### Final Merge Order
1. Core profile (always on)
2. Auto-detected profiles
3. Global config
4. Workspace config
5. `include_add` / `exclude_add`
6. `include_remove` / `exclude_remove`

### Key Schema
- `include_add`
- `exclude_add`
- `include_remove`
- `exclude_remove`

### Ignore Rules
- `.sariignore` at workspace root
- Applied to auto-detection and indexing
- Depth limit for auto-detection: 2-3 levels
- Optional project boundary marker: `.sariroot`

### Auto-Detect Safety
- Default to manual-only mode (auto-detect as recommendations)
- Auto-detect can be promoted via explicit `.sari/config.json` opt-in

## Profiles
### core (always on)
- Extensions: `.md` `.mdx` `.yaml` `.yml` `.json` `.toml` `.ini` `.cfg` `.conf` `.properties`
- Filenames: `.env`, `Makefile`, `Dockerfile`
- Globs: `.env.*`

### web
- Extensions: `.js` `.jsx` `.ts` `.tsx` `.html` `.css` `.scss` `.less` `.vue` `.svelte` `.astro` `.graphql` `.gql`
- Filenames: `package.json`, `tsconfig.json`, `vite.config.*`, `webpack.config.*`, `next.config.*`, `nuxt.config.*`

### python
- Extensions: `.py` `.pyi` `.ipynb`
- Filenames: `pyproject.toml`, `requirements.txt`, `Pipfile`, `setup.py`

### java
- Extensions: `.java` `.kt` `.kts` `.gradle` `.xml`
- Filenames: `pom.xml`, `build.gradle`, `settings.gradle`, `gradle.properties`

### go
- Extensions: `.go`
- Filenames: `go.mod`, `go.sum`

### rust
- Extensions: `.rs`
- Filenames: `Cargo.toml`, `Cargo.lock`

### cpp
- Extensions: `.c` `.h` `.cpp` `.hpp` `.cc` `.cxx` `.hh` `.hxx`
- Filenames: `CMakeLists.txt`

### csharp
- Extensions: `.cs`
- Filenames: `.sln`, `.csproj`, `.fsproj`

### ruby
- Extensions: `.rb` `.erb`
- Filenames: `Gemfile`, `Rakefile`

### php
- Extensions: `.php`
- Filenames: `composer.json`

### swift
- Extensions: `.swift` `.m` `.mm`
- Filenames: `Package.swift`

### scala
- Extensions: `.scala` `.sbt`

### dart
- Extensions: `.dart`
- Filenames: `pubspec.yaml`

### lua
- Extensions: `.lua`

### shell
- Extensions: `.sh` `.bash` `.zsh` `.fish`
- Filenames: `.bashrc`, `.zshrc`

### infra
- Extensions: `.tf` `.tfvars` `.hcl` `.yaml` `.yml`
- Filenames: `Dockerfile`, `docker-compose.yml`

### proto
- Extensions: `.proto`

### docs
- Extensions: `.md` `.mdx` `.rst` `.adoc`

### sql
- Extensions: `.sql`

## Auto-Detection Rules
- web: `package.json`, `tsconfig.json`, `vite.config.*`, `webpack.config.*`, `next.config.*`, `nuxt.config.*`
- python: `pyproject.toml`, `requirements.txt`, `Pipfile`, `setup.py`
- java: `pom.xml`, `build.gradle`, `settings.gradle`, `gradle.properties`
- go: `go.mod`, `go.sum`
- rust: `Cargo.toml`
- cpp: `CMakeLists.txt`, `meson.build`
- csharp: `*.sln`, `*.csproj`, `*.fsproj`
- ruby: `Gemfile`, `Rakefile`
- php: `composer.json`
- swift: `Package.swift`, `*.xcodeproj`, `*.xcworkspace`
- scala: `build.sbt`
- dart: `pubspec.yaml`
- lua: any `*.lua`
- shell: any `*.sh` or `.bashrc` or `.zshrc`
- infra: `Dockerfile`, `docker-compose.yml`, `*.tf`, `*.tfvars`
- proto: any `*.proto`
- docs: `README.md` or `docs/` directory
- sql: any `*.sql`

## Architecture
### Data Model
- Single DB with `root_id` tenancy
- Add `roots` table
- Add `root_id` to `files`, `symbols`, `relations`, `snippets`

### Root-Aware Querying
- All SQL must pass through root-aware query helpers
- Direct raw SQL usage is disallowed for cross-root safety
- Provide `apply_root_filter(sql, root_id)` helper in `sari/sari/core/db/main.py`

### Engine
- Embedded (Tantivy) as primary search engine
- Single global index (no roots_hash sharding)
- `root_id` filter in query (no post-filter)

### Sharding Fallback
- Index path policy must allow switching between global and per-root shards
- Default is global; fallback to shards if noisy-neighbor issues appear

### Engine Memory Controls
- Explicit segment merge policy
- Configurable memory caps for indexing and query
- Root-weighted query filtering to reduce noisy-neighbor effects

### Indexing Pipeline
Watcher -> Debounce/Coalesce -> Priority Queue -> Workers -> DB/Engine Commit

### Scheduling
- Aging Priority Queue
- Weighted Fair Queueing (per root)
- Search-first throttling

### Read Priority (SQLite)
- Search requests trigger write-yield behavior
- Writes are chunked into smaller transactions under read pressure
- DBWriter can reduce batch size on demand

### Parallelization
- Default `index_workers=2`
- Parse/document generation in parallel
- Batch commit to DB and engine

### Memory Controls
- `SARI_INDEX_MEM_MB` for overall indexing memory budget
- `SARI_INDEX_WORKERS` to override worker count
- `SARI_ENGINE_INDEX_MEM_MB` for engine indexing memory
- `SARI_ENGINE_MEM_MB` for total engine memory
- Batch sizes and worker counts adapt to the budget

## Algorithms (Included)
- Aging Priority Queue (starvation prevention)
- Weighted Fair Queueing (fairness per root)
- Content Hash Cache (skip unchanged)
- Delta Indexing (only update deltas)
- Adaptive Debounce
- Token Bucket rate limiting
- Adaptive Batch Commit
- Write Coalescing
- Query Rewrite
- Field Weighting
- Incremental AST (Tree-sitter)

## Embeddings Consistency
- Embeddings are versioned against `content_hash` and `model`
- Search results expose embedding staleness state
- Embedding generation is rate-limited in a separate queue

## LLM Context Budget
- Response layer enforces token budget
- Large graphs/artifacts are summarized first
- Detailed payloads require explicit follow-up request

## Migration Plan
1. Schema migration (add `roots`, add `root_id` columns)
2. Reindex (rebuild global index)
3. Switch query filter to `root_id` (remove post-filter)
4. Cleanup legacy index dirs

### Wipe-and-Rebuild Policy
- If schema version mismatches, delete old DB and rebuild
- No backward compatibility guaranteed

## Testing
### Unit
- Config merge (auto-detect + add/remove)
- Queue scheduling (aging/fairness)
- Hash cache + delta indexing

### Integration
- Watcher -> Indexer -> DB -> Engine
- Multi-root fairness

### Performance
- Initial indexing time
- Burst event handling
- Search response latency
