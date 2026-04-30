create table if not exists source_snapshot_rows (
  snapshot_id text not null references source_snapshots(snapshot_id) on delete cascade,
  client_id text not null,
  module text not null,
  row_index integer not null,
  row_key text not null default '',
  customs_code text not null default '',
  product_code text not null default '',
  transaction_key text not null default '',
  direction text not null default '',
  declaration_no text not null default '',
  line_no text not null default '',
  declaration_type text not null default '',
  item_code text not null default '',
  hs_code text not null default '',
  invoice_ref text not null default '',
  payload jsonb not null,
  indexed_at timestamptz not null default now(),
  primary key (snapshot_id, row_index)
);

create index if not exists source_snapshot_rows_client_module_idx
  on source_snapshot_rows (client_id, module, snapshot_id, row_index);

create index if not exists source_snapshot_rows_lookup_idx
  on source_snapshot_rows (
    client_id, module, row_key, customs_code, product_code,
    transaction_key, declaration_no, line_no, item_code
  );

create table if not exists source_version_rows (
  version_id text not null references source_versions(version_id) on delete cascade,
  client_id text not null,
  module text not null,
  row_index integer not null,
  row_key text not null default '',
  customs_code text not null default '',
  product_code text not null default '',
  transaction_key text not null default '',
  direction text not null default '',
  declaration_no text not null default '',
  line_no text not null default '',
  declaration_type text not null default '',
  item_code text not null default '',
  hs_code text not null default '',
  invoice_ref text not null default '',
  payload jsonb not null,
  indexed_at timestamptz not null default now(),
  primary key (version_id, row_index)
);

create index if not exists source_version_rows_client_module_idx
  on source_version_rows (client_id, module, version_id, row_index);

create index if not exists source_version_rows_lookup_idx
  on source_version_rows (
    client_id, module, row_key, customs_code, product_code,
    transaction_key, declaration_no, line_no, item_code
  );
