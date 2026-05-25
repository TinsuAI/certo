-- CO stock events: audit log per lot.
-- Every state change to a lot's (used_qty, opening_qty_override) is recorded
-- as an event row. Sources include:
--   - adjustment_import_insert / adjustment_import_update / adjustment_void
--     (manual workbook upload via /co-stock/import)
--   - claim_lock / claim_release
--     (sheet lock or unlock via /co-case ... /origin/sheet/.../lock)
--
-- See app/co_stock_events_store.py for the write/read API and
-- /clients/{id}/co-stock/lot-history endpoint for the per-lot retrieval.

create table if not exists co_stock_events (
  event_id text primary key,
  client_id text not null,
  declaration_no text not null,
  line_no text not null,
  customs_code text not null,
  event_type text not null check (event_type in (
    'adjustment_import_insert',
    'adjustment_import_update',
    'adjustment_void',
    'claim_lock',
    'claim_release'
  )),
  qty_delta numeric(28, 6),
  qty_before numeric(28, 6),
  qty_after numeric(28, 6),
  opening_qty_before numeric(28, 6),
  opening_qty_after numeric(28, 6),
  source_co_no text not null default '',
  case_id text not null default '',
  sheet_product_code text not null default '',
  source_file_ref text not null default '',
  batch_id text not null default '',
  actor text not null default 'system',
  notes text not null default '',
  recorded_at timestamptz not null default now()
);

-- Hot path: per-lot history modal — newest first.
create index if not exists co_stock_events_lookup_idx
  on co_stock_events (client_id, declaration_no, line_no, customs_code, recorded_at desc);

-- "What did this case touch" + audit.
create index if not exists co_stock_events_case_idx
  on co_stock_events (client_id, case_id, recorded_at desc);

-- "Which lots did this import touch" + audit / void by batch.
create index if not exists co_stock_events_batch_idx
  on co_stock_events (client_id, batch_id, recorded_at desc);
