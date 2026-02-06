# Event Bus Types

The internal `EventBus` publishes lightweight events for plugins and observers.
All events are best-effort; handlers must be fast and non-blocking.

## Topics

- `fs_event`
  - Payload: `{ kind, path, dest_path, ts, root }` (see `FsEvent`)
  - Emitted by `FileWatcher` when filesystem changes are detected.

- `file_indexed`
  - Payload: `{ path, root_id }`
  - Emitted when a file is processed and enqueued for DB upsert.

- `file_unchanged`
  - Payload: `{ path, root_id }`
  - Emitted when file metadata indicates no change.

- `file_skipped`
  - Payload: `{ path, root_id, reason }`
  - Emitted when parsing is skipped (e.g., too large, empty).

- `ast_skipped`
  - Payload: `{ path, root_id, reason }`
  - Emitted when AST parsing is skipped or fails.

- `file_error`
  - Payload: `{ path, root_id }`
  - Emitted when processing fails unexpectedly.

- `db_commit`
  - Payload: `{ ts, files, symbols, relations, snippets, contexts, deleted, failed }`
  - Emitted after a DBWriter transaction commit.

## Notes
- Event ordering is not guaranteed across threads.
- Handlers should avoid slow work; offload heavy tasks to queues.
