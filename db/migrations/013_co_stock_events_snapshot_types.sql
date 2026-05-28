-- Extend the co_stock_events CHECK constraint to accept materializer-emitted
-- audit rows: snapshot_row_added / _removed / _updated. See option B in
-- `.ai/features/2026-05-28-co-stock-refresh-audit.md` for the rationale.

alter table co_stock_events
  drop constraint if exists co_stock_events_event_type_check;

alter table co_stock_events
  add constraint co_stock_events_event_type_check
  check (event_type in (
    'adjustment_import_insert',
    'adjustment_import_update',
    'adjustment_void',
    'claim_lock',
    'claim_release',
    'snapshot_row_added',
    'snapshot_row_removed',
    'snapshot_row_updated'
  ));
