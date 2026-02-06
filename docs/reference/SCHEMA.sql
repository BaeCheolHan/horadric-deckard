-- Sari DB schema (redesign)

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS roots (
  root_id TEXT PRIMARY KEY,
  root_path TEXT NOT NULL,
  real_path TEXT NOT NULL,
  label TEXT DEFAULT '',
  state TEXT DEFAULT 'active',
  config_json TEXT DEFAULT '{}',
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY, -- root_id/rel_path
  rel_path TEXT NOT NULL,
  root_id TEXT NOT NULL,
  repo TEXT NOT NULL,
  mtime INTEGER NOT NULL,
  size INTEGER NOT NULL,
  content BLOB NOT NULL,
  content_hash TEXT DEFAULT '',
  fts_content TEXT DEFAULT '',
  last_seen INTEGER DEFAULT 0,
  deleted_ts INTEGER DEFAULT 0,
  parse_status TEXT NOT NULL DEFAULT 'none',
  parse_reason TEXT NOT NULL DEFAULT 'none',
  ast_status TEXT NOT NULL DEFAULT 'none',
  ast_reason TEXT NOT NULL DEFAULT 'none',
  is_binary INTEGER NOT NULL DEFAULT 0,
  is_minified INTEGER NOT NULL DEFAULT 0,
  sampled INTEGER NOT NULL DEFAULT 0,
  content_bytes INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT DEFAULT '{}',
  FOREIGN KEY(root_id) REFERENCES roots(root_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS symbols (
  symbol_id TEXT,
  path TEXT NOT NULL,
  root_id TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  content TEXT NOT NULL,
  parent_name TEXT DEFAULT '',
  metadata TEXT DEFAULT '{}',
  docstring TEXT DEFAULT '',
  qualname TEXT DEFAULT '',
  PRIMARY KEY (root_id, path, name, line),
  FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS symbol_relations (
  from_path TEXT NOT NULL,
  from_root_id TEXT NOT NULL,
  from_symbol TEXT NOT NULL,
  from_symbol_id TEXT DEFAULT '',
  to_path TEXT NOT NULL,
  to_root_id TEXT NOT NULL,
  to_symbol TEXT NOT NULL,
  to_symbol_id TEXT DEFAULT '',
  rel_type TEXT NOT NULL,
  line INTEGER NOT NULL,
  metadata_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS embeddings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  root_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT DEFAULT 'ready',
  vector BLOB NOT NULL,
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL,
  FOREIGN KEY(root_id) REFERENCES roots(root_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  root_id TEXT NOT NULL,
  type TEXT NOT NULL,
  params_json TEXT DEFAULT '{}',
  status TEXT DEFAULT 'pending',
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL,
  FOREIGN KEY(root_id) REFERENCES roots(root_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  root_id TEXT NOT NULL,
  type TEXT NOT NULL,
  version TEXT DEFAULT '',
  payload_json TEXT NOT NULL,
  created_ts INTEGER NOT NULL,
  FOREIGN KEY(root_id) REFERENCES roots(root_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS graphs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  root_id TEXT NOT NULL,
  name TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_ts INTEGER NOT NULL,
  FOREIGN KEY(root_id) REFERENCES roots(root_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS snippets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag TEXT NOT NULL,
  path TEXT NOT NULL,
  root_id TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  anchor_before TEXT DEFAULT '',
  anchor_after TEXT DEFAULT '',
  repo TEXT DEFAULT '',
  note TEXT DEFAULT '',
  commit_hash TEXT DEFAULT '',
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL,
  metadata_json TEXT DEFAULT '{}',
  FOREIGN KEY(root_id) REFERENCES roots(root_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contexts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL UNIQUE,
  content TEXT NOT NULL,
  tags_json TEXT DEFAULT '[]',
  related_files_json TEXT DEFAULT '[]',
  source TEXT DEFAULT '',
  valid_from INTEGER DEFAULT 0,
  valid_until INTEGER DEFAULT 0,
  deprecated INTEGER DEFAULT 0,
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS failed_tasks (
  path TEXT PRIMARY KEY,
  root_id TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL,
  ts INTEGER NOT NULL,
  next_retry INTEGER NOT NULL,
  metadata_json TEXT DEFAULT '{}',
  FOREIGN KEY(root_id) REFERENCES roots(root_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS engine_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_ts INTEGER NOT NULL
);

-- Optional FTS (enabled only when SARI_ENABLE_FTS=1)
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(root_id, rel_path, repo, content, content='files', content_rowid='rowid');

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
  INSERT INTO files_fts(rowid, root_id, rel_path, repo, content)
  VALUES (new.rowid, new.root_id, new.rel_path, new.repo, new.content);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, root_id, rel_path, repo, content)
  VALUES ('delete', old.rowid, old.root_id, old.rel_path, old.repo, old.content);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, root_id, rel_path, repo, content)
  VALUES ('delete', old.rowid, old.root_id, old.rel_path, old.repo, old.content);
  INSERT INTO files_fts(rowid, root_id, rel_path, repo, content)
  VALUES (new.rowid, new.root_id, new.rel_path, new.repo, new.content);
END;
