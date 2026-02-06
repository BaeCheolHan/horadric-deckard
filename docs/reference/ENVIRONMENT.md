# Environment Variables

## Indexing / Performance
- `SARI_INDEX_MEM_MB`: Overall indexing memory budget (MB)
- `SARI_INDEX_WORKERS`: Override index worker count
- `SARI_ENGINE_MEM_MB`: Total embedded engine memory (MB)
- `SARI_ENGINE_INDEX_MEM_MB`: Embedded engine indexing memory (MB)
- `SARI_ENGINE_THREADS`: Embedded engine thread count
- `SARI_ENGINE_MAX_DOC_BYTES`: Max document bytes to index
- `SARI_ENGINE_PREVIEW_BYTES`: Preview bytes per document
- `SARI_ENGINE_INDEX_POLICY`: global|roots_hash|per_root

## Watcher / Queue
- `SARI_GIT_CHECKOUT_DEBOUNCE`: Git event debounce seconds
- `SARI_WATCHER_MONITOR_SECONDS`: Watcher health check interval
- `SARI_COALESCE_SHARDS`: Coalesce shard count
- `SARI_DEBOUNCE_MIN_MS`: Minimum debounce (ms)
- `SARI_DEBOUNCE_MAX_MS`: Maximum debounce (ms)
- `SARI_DEBOUNCE_TARGET_RPS`: Target events per second before scaling debounce
- `SARI_DEBOUNCE_RATE_WINDOW`: Rate window seconds for debounce
- `SARI_EVENT_BUCKET_CAPACITY`: Token bucket capacity for file events
- `SARI_EVENT_BUCKET_RATE`: Token bucket refill rate (tokens/sec)
- `SARI_EVENT_BUCKET_FLUSH_MS`: Burst flush interval (ms)

## Config / Paths
- `SARI_CONFIG`: Override config path
- `SARI_DATA_DIR`: Override global data directory
- `SARI_AST_CACHE_ENTRIES`: AST cache entries for incremental parsing
- `SARI_STORE_CONTENT`: Store full file content in SQLite (default true)
- `SARI_STORE_CONTENT_COMPRESS`: Compress stored content with zlib (default false)
- `SARI_STORE_CONTENT_COMPRESS_LEVEL`: Compression level 1-9 (default 3)
- `SARI_ENABLE_FTS`: Enable SQLite FTS index (default false)
- `SARI_ENGINE_RELOAD_MS`: Tantivy reader reload interval in ms (default 1000)
- `SARI_SNIPPET_MAX_BYTES`: Max bytes for snippet extraction (default 200000)
- `SARI_SNIPPET_CACHE_SIZE`: LRU cache size for snippets (default 128)
- `SARI_FTS_REBUILD_ON_START`: Rebuild FTS index on startup (default false)
- `SARI_HTTP_RATE_LIMIT`: HTTP requests per second (default 50)
- `SARI_HTTP_RATE_BURST`: HTTP rate burst tokens (default 100)
- `SARI_HTTP_LOG_ENABLED`: Enable HTTP request logging (default true)
- `SARI_FTS_MAX_BYTES`: Max bytes indexed into FTS (default 1000000)
- `SARI_REGISTRY_IDLE_SEC`: Idle seconds before workspace registry eviction (default 900)

## Engine / Install
- `SARI_ENGINE_MODE`: embedded|sqlite
- `SARI_ENGINE_AUTO_INSTALL`: auto-install embedded engine
- `SARI_ENGINE_PACKAGE`: override engine package

## Networking
- `SARI_ALLOW_NON_LOOPBACK`: Allow non-loopback binding

## Logging / Output
- `SARI_RESPONSE_COMPACT`: pack output on/off
