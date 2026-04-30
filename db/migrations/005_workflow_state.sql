create table if not exists bom_states (
  client_id text primary key,
  schema_version integer not null default 1,
  config jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists bom_uploads (
  client_id text not null,
  upload_id text not null,
  original_filename text not null default '',
  safe_filename text not null default '',
  stored_filename text not null default '',
  stored_path text not null default '',
  storage_backend text not null default '',
  content_sha256 text not null default '',
  size_bytes bigint not null default 0,
  file_ext text not null default '',
  mime_type text not null default '',
  profile_used text not null default '',
  upload_mode text not null default '',
  upload_scope text not null default '',
  parse_status text not null default '',
  parse_error text not null default '',
  result text not null default '',
  snapshot_id text not null default '',
  normalized_hash text not null default '',
  row_count integer not null default 0,
  created_version_id text not null default '',
  created_aggregate_version_no integer not null default 0,
  duplicate_of text not null default '',
  diff_summary jsonb not null default '{}'::jsonb,
  product_results jsonb not null default '[]'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  primary key (client_id, upload_id)
);

create index if not exists bom_uploads_client_created_idx
  on bom_uploads (client_id, created_at desc);

create table if not exists bom_snapshots (
  client_id text not null,
  snapshot_id text not null,
  upload_id text not null default '',
  profile text not null default '',
  upload_mode text not null default '',
  normalized_hash text not null default '',
  row_count integer not null default 0,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  primary key (client_id, snapshot_id)
);

create table if not exists bom_snapshot_rows (
  client_id text not null,
  snapshot_id text not null,
  row_index integer not null,
  row_key text not null default '',
  product_code text not null default '',
  bom_code text not null default '',
  bom_variant_id text not null default '',
  material_code text not null default '',
  uom text not null default '',
  payload jsonb not null,
  indexed_at timestamptz not null default now(),
  primary key (client_id, snapshot_id, row_index)
);

create index if not exists bom_snapshot_rows_lookup_idx
  on bom_snapshot_rows (client_id, product_code, material_code, row_key);

create table if not exists bom_product_versions (
  client_id text not null,
  product_version_id text not null,
  product_code text not null default '',
  product_version_no integer not null default 0,
  status text not null default '',
  source_snapshot_id text not null default '',
  source_upload_id text not null default '',
  previous_product_version_id text not null default '',
  profile text not null default '',
  version_hash text not null default '',
  row_count integer not null default 0,
  diff_summary jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  published_at timestamptz not null default now(),
  primary key (client_id, product_version_id)
);

create index if not exists bom_product_versions_lookup_idx
  on bom_product_versions (client_id, product_code, product_version_no desc);

create table if not exists bom_product_version_rows (
  client_id text not null,
  product_version_id text not null,
  row_index integer not null,
  row_key text not null default '',
  product_code text not null default '',
  bom_code text not null default '',
  bom_variant_id text not null default '',
  material_code text not null default '',
  uom text not null default '',
  payload jsonb not null,
  indexed_at timestamptz not null default now(),
  primary key (client_id, product_version_id, row_index)
);

create table if not exists bom_versions (
  client_id text not null,
  version_id text not null,
  version_no integer not null default 0,
  aggregate_version_no integer not null default 0,
  status text not null default '',
  source_snapshot_id text not null default '',
  source_upload_id text not null default '',
  previous_version_id text not null default '',
  version_hash text not null default '',
  composition_hash text not null default '',
  row_count integer not null default 0,
  changed_products jsonb not null default '[]'::jsonb,
  diff_summary jsonb not null default '{}'::jsonb,
  product_versions jsonb not null default '[]'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  published_at timestamptz not null default now(),
  primary key (client_id, version_id)
);

create index if not exists bom_versions_client_version_idx
  on bom_versions (client_id, version_no desc);

create table if not exists bom_version_rows (
  client_id text not null,
  version_id text not null,
  row_index integer not null,
  row_key text not null default '',
  product_code text not null default '',
  bom_code text not null default '',
  bom_variant_id text not null default '',
  material_code text not null default '',
  uom text not null default '',
  payload jsonb not null,
  indexed_at timestamptz not null default now(),
  primary key (client_id, version_id, row_index)
);

create table if not exists bom_audit_events (
  client_id text not null,
  audit_event_id text not null,
  event text not null default '',
  actor text not null default '',
  details jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  occurred_at timestamptz not null default now(),
  primary key (client_id, audit_event_id)
);

create index if not exists bom_audit_events_client_time_idx
  on bom_audit_events (client_id, occurred_at desc);

create table if not exists co_case_states (
  client_id text primary key,
  schema_version integer not null default 1,
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists co_cases (
  client_id text not null,
  case_id text not null,
  title text not null default '',
  case_code text not null default '',
  destination_market text not null default '',
  agreement text not null default '',
  co_form_type text not null default '',
  rule text not null default '',
  invoice_no text not null default '',
  bill_of_lading_no text not null default '',
  supporting_file_count integer not null default 0,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (client_id, case_id)
);

create index if not exists co_cases_client_updated_idx
  on co_cases (client_id, updated_at desc);

create table if not exists co_supporting_files (
  client_id text not null,
  case_id text not null,
  upload_id text not null,
  slot text not null default '',
  original_filename text not null default '',
  safe_filename text not null default '',
  stored_filename text not null default '',
  stored_path text not null default '',
  storage_backend text not null default '',
  content_sha256 text not null default '',
  size_bytes bigint not null default 0,
  file_ext text not null default '',
  mime_type text not null default '',
  invoice_no text not null default '',
  bill_of_lading_no text not null default '',
  payload jsonb not null,
  uploaded_at timestamptz not null default now(),
  primary key (client_id, case_id, upload_id)
);

create index if not exists co_supporting_files_lookup_idx
  on co_supporting_files (client_id, case_id, slot, invoice_no, bill_of_lading_no);
