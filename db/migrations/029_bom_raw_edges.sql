-- 029_bom_raw_edges.sql
-- Store technical/raw BOM as graph edges alongside existing flat/manual rows.
-- `bom_versions` remains the common version/provenance table:
--   technical_raw        -> hub.bom_edges
--   technical_flattened,
--   manual_flat,
--   staff_edit           -> hub.bom_version_rows

create table if not exists hub.bom_edges (
  version_id text not null references hub.bom_versions(version_id) on delete cascade,
  row_index integer not null,
  root_code text not null,
  parent_code text not null,
  child_code text not null,
  qty_per_parent numeric(20,9) not null,
  uom text,
  level integer,
  node_path text,
  sheet_name text,
  source_row_no integer,
  payload jsonb not null default '{}'::jsonb,
  primary key (version_id, row_index),
  constraint chk_bom_edges_qty_positive check (qty_per_parent > 0)
);

create index if not exists idx_bom_edges_root
  on hub.bom_edges(root_code);

create index if not exists idx_bom_edges_parent
  on hub.bom_edges(parent_code);

create index if not exists idx_bom_edges_child
  on hub.bom_edges(child_code);
