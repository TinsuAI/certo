-- Material registry per DNCX. Five-value category enum from BCQT vocabulary.

create table if not exists hub.materials (
  dncx_id text not null references hub.dncxs(dncx_id) on delete cascade,
  customs_code text not null,
  product_code text,
  name text,
  category text not null,
  category_override text,
  override_reason text,
  status text not null default 'active',
  unit text,
  hs_code text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (dncx_id, customs_code),
  constraint chk_category check (category in ('nvl','btp_sx','btp_nm','tp','ccdc')),
  constraint chk_status check (status in ('active','discontinued'))
);

create index if not exists idx_materials_category on hub.materials(dncx_id, category);
create index if not exists idx_materials_product_code on hub.materials(dncx_id, product_code);
create index if not exists idx_materials_hs on hub.materials(dncx_id, hs_code);

-- Per-material change log.
create table if not exists hub.material_audit_events (
  event_id bigserial primary key,
  dncx_id text not null,
  customs_code text not null,
  event_type text not null,
  actor text,
  payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists idx_material_audit on hub.material_audit_events(dncx_id, customs_code, occurred_at desc);
