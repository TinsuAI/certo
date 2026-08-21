-- Generic file upload tracking (Materials, BCCT, BOM, Code Mappings all reference this).
create table if not exists hub.file_uploads (
  upload_id text primary key,
  dncx_id text references hub.dncxs(dncx_id) on delete set null,
  module text not null,
  original_filename text not null,
  stored_path text not null,
  storage_backend text not null default 'localfs',
  content_sha256 text not null,
  size_bytes bigint not null,
  mime_type text,
  uploader_user_id text,
  parse_status text not null default 'pending',
  parse_error text,
  row_count integer,
  result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  parsed_at timestamptz,
  constraint chk_module check (module in ('materials','bcct','bom','code_mappings'))
);

create index if not exists idx_file_uploads_dncx on hub.file_uploads(dncx_id, module, created_at desc);
create index if not exists idx_file_uploads_sha on hub.file_uploads(content_sha256);
