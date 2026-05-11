-- CO stock ledger: per-claim consumption tracking across cases.
-- See app/co_stock_ledger.py + .ai/api-requests/2026-05-13-bcct-by-codes-lookup.md
-- for the architecture: BCCT (Data Hub) owns available_qty, this table owns
-- claim events (lock/release) so remaining_qty can be computed cross-case.

create table if not exists co_stock_claims (
  claim_id text primary key,
  client_id text not null,
  case_id text not null,
  sheet_product_code text not null,
  source_row text not null,
  material_code text not null default '',
  material_index integer not null default 0,
  claimed_qty numeric(20, 6) not null default 0,
  status text not null check (status in ('locked', 'released')),
  locked_at timestamptz not null default now(),
  released_at timestamptz
);

-- Hot path: "what's currently locked against this lot for this client"
-- (substitute modal, sheet calc cross-case check).
create index if not exists co_stock_claims_client_lot_status_idx
  on co_stock_claims (client_id, source_row, status);

-- Hot path: "all claims for this case" (release on unlock, audit).
create index if not exists co_stock_claims_client_case_idx
  on co_stock_claims (client_id, case_id);

-- Hot path: "all claims for this sheet" (replace on re-lock).
create index if not exists co_stock_claims_sheet_idx
  on co_stock_claims (client_id, case_id, sheet_product_code);
