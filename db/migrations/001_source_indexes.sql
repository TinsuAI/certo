create table if not exists source_index_metadata (
  client_id text not null,
  module text not null,
  version_id text not null default '',
  version_no integer not null default 0,
  published_row_count integer not null default 0,
  reviewed_row_count integer not null default 0,
  correction_candidate_count integer not null default 0,
  state_mtime_ns bigint not null default 0,
  config_hash text not null default '',
  indexed_at timestamptz not null default now(),
  primary key (client_id, module)
);

create table if not exists bcct_rows (
  client_id text not null,
  transaction_key text not null,
  direction text not null default '',
  review_status text not null default '',
  declaration_no text not null default '',
  line_no text not null default '',
  declaration_type text not null default '',
  item_code text not null default '',
  hs_code text not null default '',
  quantity text not null default '',
  unit text not null default '',
  invoice_ref text not null default '',
  payload jsonb not null,
  indexed_at timestamptz not null default now(),
  primary key (client_id, transaction_key)
);

create index if not exists bcct_rows_export_lookup_idx
  on bcct_rows (client_id, direction, review_status, declaration_type);

create index if not exists bcct_rows_declaration_idx
  on bcct_rows (client_id, declaration_no, line_no);

create index if not exists bcct_rows_item_hs_idx
  on bcct_rows (client_id, item_code, hs_code);

create table if not exists bcct_invoice_index (
  client_id text not null,
  invoice_key text not null,
  transaction_key text not null,
  primary key (client_id, invoice_key, transaction_key),
  foreign key (client_id, transaction_key)
    references bcct_rows (client_id, transaction_key)
    on delete cascade
);

create index if not exists bcct_invoice_index_lookup_idx
  on bcct_invoice_index (client_id, invoice_key);

create table if not exists co_stock_rows (
  client_id text not null,
  source_row text not null,
  transaction_key text not null default '',
  import_declaration_no text not null default '',
  line_no text not null default '',
  declaration_type text not null default '',
  customs_item_code text not null default '',
  allocation_code text not null default '',
  eligibility_status text not null default '',
  remaining_qty text not null default '',
  payload jsonb not null,
  indexed_at timestamptz not null default now(),
  primary key (client_id, source_row)
);

create index if not exists co_stock_rows_lookup_idx
  on co_stock_rows (client_id, import_declaration_no, line_no, customs_item_code);

create index if not exists co_stock_rows_allocation_idx
  on co_stock_rows (client_id, allocation_code, eligibility_status);
