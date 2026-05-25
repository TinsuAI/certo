-- Add lookup-key columns to co_stock_claims so we can emit per-lot
-- (declaration_no, line_no, customs_code) audit events on lock/release
-- without an extra BCCT lookup. Existing rows get blank values. The next
-- lock cycle backfills them. Events for legacy claims will be skipped
-- (events_store requires non-empty key).

alter table co_stock_claims
  add column if not exists declaration_no text not null default '',
  add column if not exists line_no text not null default '',
  add column if not exists customs_code text not null default '';

create index if not exists co_stock_claims_lot_key_idx
  on co_stock_claims (client_id, declaration_no, line_no, customs_code, status);
