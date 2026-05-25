-- CO stock adjustments: per-lot opening/used overrides imported from agency
-- workbooks (the legacy "tru lui CO" Save sheet) or entered manually. Layered
-- on top of BCCT-derived stock (Data Hub) AFTER co_stock_claims.
--
-- See app/co_stock_adjustments_store.py for the apply logic and
-- scripts/convert_co_stock.py for the converter that turns the agency
-- workbook into the standard template.
--
-- Snapshot model: each (client_id, declaration_no, line_no, customs_code)
-- has exactly one active adjustment row. Re-import overwrites. batch_id and
-- source_file_ref keep an audit trail of which upload last touched a row.

create table if not exists co_stock_adjustments (
  adjustment_id text primary key,
  client_id text not null,
  declaration_no text not null,
  line_no text not null,
  customs_code text not null,
  declaration_type text not null default '',
  registration_date date,
  hs_code text not null default '',
  goods_name text not null default '',
  origin_country text not null default '',
  unit text not null default '',
  partner text not null default '',
  invoice_no text not null default '',
  invoice_date date,
  unit_price numeric(28, 8),
  taxable_unit_price numeric(28, 8),
  exchange_rate numeric(20, 6),
  opening_qty_override numeric(28, 6),
  used_qty numeric(28, 6) not null default 0,
  source_co_no text not null default '',
  source_file_ref text not null default '',
  batch_id text not null default '',
  status text not null default 'active' check (status in ('active', 'voided')),
  notes text not null default '',
  recorded_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, declaration_no, line_no, customs_code)
);

-- Hot path: "give me all adjustments for this client to apply at stock-pool
-- build time" (substitute modal + sheet calc + export).
create index if not exists co_stock_adjustments_client_status_idx
  on co_stock_adjustments (client_id, status);

-- Hot path: targeted lookup by composite key when re-upserting.
create index if not exists co_stock_adjustments_lookup_idx
  on co_stock_adjustments (client_id, declaration_no, line_no, customs_code);

-- Audit: list/void a whole batch.
create index if not exists co_stock_adjustments_batch_idx
  on co_stock_adjustments (client_id, batch_id);
