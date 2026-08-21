-- N-N mapping table per DNCX (BQD = Bảng Quy Đổi). No priority column — priority
-- comes from BCCT-aggregate resolution at code_mapping_resolutions level.

create table if not exists hub.code_mappings (
  dncx_id text not null references hub.dncxs(dncx_id) on delete cascade,
  internal_code text not null,
  customs_code text not null,
  category text,
  notes text,
  created_at timestamptz not null default now(),
  primary key (dncx_id, internal_code, customs_code),
  constraint chk_mapping_category check (category is null or category in ('nvl','tp','ccdc'))
);

create index if not exists idx_code_mappings_internal on hub.code_mappings(dncx_id, internal_code);
create index if not exists idx_code_mappings_customs on hub.code_mappings(dncx_id, customs_code);

-- Materialized resolution output (one primary HQ code per internal code, after disambiguation).
create table if not exists hub.code_mapping_resolutions (
  dncx_id text not null references hub.dncxs(dncx_id) on delete cascade,
  internal_code text not null,
  resolved_customs_code text not null,
  resolution_basis text not null,
  resolved_at timestamptz not null default now(),
  details jsonb not null default '{}'::jsonb,
  primary key (dncx_id, internal_code),
  constraint chk_resolution_basis check (resolution_basis in (
    'identity', 'bqd_unique', 'bcct_qty_pick', 'manual_override', 'fallback'
  ))
);

create index if not exists idx_resolutions_customs on hub.code_mapping_resolutions(dncx_id, resolved_customs_code);
