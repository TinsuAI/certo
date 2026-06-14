-- Drop the legacy co_stock_adjustments table (created by migration 008).
--
-- The static off-app baseline is no longer folded onto BCCT-derived stock.
-- The CO-stock model is now strictly layered, computed at read time by
-- co_stock_ledger.apply_used_qty:
--   remaining = opening_qty (Data Hub BCCT)
--             − baseline_used_qty (baked directly by the standalone
--               workbook-snapshot import, /co-stock/import-snapshot)
--             − live ledger claims (co_stock_claims).
--
-- The fold_baseline / aggregate_by_lookup_key / refold_* machinery, the
-- /co-stock/import overlay route, and app/co_stock_adjustments_store.py were
-- removed, so this table is unused. Off-app consumption now enters only via
-- the workbook snapshot (which bakes baseline_used_qty per lot at import).

drop table if exists co_stock_adjustments;
