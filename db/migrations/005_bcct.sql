-- BCCT (customs declaration registry) rows. internal_code is parsed from goods name
-- per DNCX rules at ingestion (Growatt: regex from Tên hàng; identity DNCXs: equals customs_code).

create table if not exists hub.bcct_rows (
  dncx_id text not null references hub.dncxs(dncx_id) on delete cascade,
  year integer not null,
  transaction_key text not null,
  line_no text not null default '0',
  declaration_no text,
  declaration_type text,
  direction text,
  registration_date date,
  customs_code text,
  internal_code text,
  goods_name text,
  hs_code text,
  quantity numeric(20,6),
  unit text,
  quantity_2 numeric(20,6),
  unit_2 text,
  unit_price numeric(20,6),
  total_value numeric(20,6),
  currency text,
  origin text,
  invoice_ref text,
  resolved_customs_code text,
  bom_version_id text,
  upload_id text references hub.file_uploads(upload_id) on delete set null,
  payload jsonb not null default '{}'::jsonb,
  indexed_at timestamptz not null default now(),
  primary key (dncx_id, year, transaction_key, line_no)
);

create index if not exists idx_bcct_internal on hub.bcct_rows(dncx_id, year, internal_code);
create index if not exists idx_bcct_customs on hub.bcct_rows(dncx_id, year, customs_code);
create index if not exists idx_bcct_resolved on hub.bcct_rows(dncx_id, year, resolved_customs_code);
create index if not exists idx_bcct_declaration on hub.bcct_rows(dncx_id, year, declaration_no, line_no);
create index if not exists idx_bcct_invoice on hub.bcct_rows(dncx_id, year, invoice_ref);
create index if not exists idx_bcct_direction on hub.bcct_rows(dncx_id, year, direction);
