create table if not exists source_module_state (
  client_id text not null,
  module text not null,
  schema_version integer not null default 1,
  latest_version_id text not null default '',
  next_version_no integer not null default 1,
  published_row_count integer not null default 0,
  upload_count integer not null default 0,
  version_count integer not null default 0,
  correction_candidate_count integer not null default 0,
  updated_at timestamptz not null default now(),
  primary key (client_id, module)
);

create table if not exists source_uploads (
  upload_id text primary key,
  client_id text not null,
  module text not null,
  metadata_schema_version integer not null default 1,
  original_filename text not null default '',
  safe_filename text not null default '',
  stored_filename text not null default '',
  stored_path text not null default '',
  storage_backend text not null default '',
  content_sha256 text not null default '',
  size_bytes bigint not null default 0,
  file_ext text not null default '',
  mime_type text not null default '',
  upload_scope text not null default '',
  parse_status text not null default '',
  parse_error text not null default '',
  snapshot_id text not null default '',
  row_count integer not null default 0,
  result text not null default '',
  created_version_id text not null default '',
  diff_summary jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists source_uploads_client_module_idx
  on source_uploads (client_id, module, created_at desc);

create table if not exists source_raw_files (
  raw_file_id text primary key,
  upload_id text not null references source_uploads(upload_id) on delete cascade,
  client_id text not null,
  module text not null,
  storage_backend text not null default '',
  storage_key text not null default '',
  filename text not null default '',
  content_sha256 text not null default '',
  size_bytes bigint not null default 0,
  content_type text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists source_snapshots (
  snapshot_id text primary key,
  client_id text not null,
  module text not null,
  upload_id text not null default '',
  row_count integer not null default 0,
  rows_hash text not null default '',
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists source_snapshots_client_module_idx
  on source_snapshots (client_id, module, created_at desc);

create table if not exists source_versions (
  version_id text primary key,
  client_id text not null,
  module text not null,
  version_no integer not null default 0,
  source_upload_id text not null default '',
  snapshot_id text not null default '',
  row_count integer not null default 0,
  rows_hash text not null default '',
  summary jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  unique (client_id, module, version_no)
);

create index if not exists source_versions_client_module_idx
  on source_versions (client_id, module, version_no desc);

create table if not exists source_audit_events (
  audit_event_id text primary key,
  client_id text not null,
  module text not null,
  event text not null default '',
  upload_id text not null default '',
  version_id text not null default '',
  snapshot_id text not null default '',
  details jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists source_audit_events_client_module_idx
  on source_audit_events (client_id, module, created_at desc);
