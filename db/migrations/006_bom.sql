-- BOM 8-table model (ported from CO) + two-axis provenance + tombstoning + proposal queue.

create table if not exists hub.bom_versions (
  version_id text primary key,
  dncx_id text not null references hub.dncxs(dncx_id) on delete cascade,
  product_code text not null,
  version_no integer not null,
  aggregate_version_no integer,
  status text not null default 'published',
  actor text not null,
  intent text not null,
  parent_version_id text references hub.bom_versions(version_id),
  parent_norm text generated always as (coalesce(parent_version_id, '00000000-0000-0000-0000-000000000000')) stored,
  context jsonb not null default '{}'::jsonb,
  source_upload_id text references hub.file_uploads(upload_id) on delete set null,
  normalized_hash text not null,
  row_count integer not null default 0,
  diff_summary jsonb not null default '{}'::jsonb,
  tombstoned_at timestamptz,
  tombstone_reason text,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  constraint chk_actor check (actor in ('agency_staff','co_system','erp_pipeline','system')),
  constraint chk_intent check (intent in ('asserted_technical','derived','modified_for_case','staff_edit')),
  constraint chk_status check (status in ('draft','published','superseded')),
  constraint uq_bom_idempotent unique (dncx_id, product_code, actor, intent, parent_norm, normalized_hash)
);

create index if not exists idx_bom_versions_product on hub.bom_versions(dncx_id, product_code, version_no desc);
create index if not exists idx_bom_versions_intent on hub.bom_versions(dncx_id, product_code, intent);
create index if not exists idx_bom_versions_alive on hub.bom_versions(dncx_id, product_code) where tombstoned_at is null;

create table if not exists hub.bom_version_rows (
  version_id text not null references hub.bom_versions(version_id) on delete cascade,
  row_index integer not null,
  material_code text not null,
  bom_code text,
  bom_variant_id text,
  qty_per_unit numeric(20,9),
  uom text,
  payload jsonb not null default '{}'::jsonb,
  primary key (version_id, row_index)
);

create index if not exists idx_bom_version_rows_material on hub.bom_version_rows(material_code);

create table if not exists hub.bom_audit_events (
  event_id bigserial primary key,
  dncx_id text not null,
  product_code text,
  version_id text,
  event_type text not null,
  actor text not null,
  details jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists idx_bom_audit on hub.bom_audit_events(dncx_id, occurred_at desc);

-- Proposal queue. Auto-only in MVP; manual mode adds reviewer endpoints in phase 2.
create table if not exists hub.bom_change_requests (
  proposal_id text primary key,
  dncx_id text not null references hub.dncxs(dncx_id) on delete cascade,
  product_code text not null,
  actor text not null,
  intent text not null,
  parent_version_id text references hub.bom_versions(version_id),
  context jsonb not null default '{}'::jsonb,
  rows_payload jsonb not null,
  normalized_hash text not null,
  status text not null default 'pending',
  decided_at timestamptz,
  decided_by text,
  decision_reason text,
  failed_conditions jsonb,
  materialized_version_id text references hub.bom_versions(version_id),
  created_at timestamptz not null default now(),
  constraint chk_request_status check (status in ('pending','approved','rejected','withdrawn'))
);

create index if not exists idx_proposals_pending on hub.bom_change_requests(dncx_id, status, created_at);
create index if not exists idx_proposals_product on hub.bom_change_requests(dncx_id, product_code, created_at desc);
