# Audit — trừ-lùi must not be a variable of system logic (2026-06-07)

## Mandate
Principle (decided 2026-06-06): the agency trừ-lùi workbook is a **stock snapshot you
sync/adjust to reality** — it must NOT drive system logic. Trigger: the kg-vs-metric-ton
unit bug (workbook qty in kg, BCCT in tonnes → folded opening in the wrong unit → 1000×
value + over-allocation risk), fixed as a DATA error (`scripts/fix_trului_unit.py`) with
`fold_baseline` kept "dumb". This audit sweeps the codebase for any *other* place where
adjustment data leaks into logic: unit conversion/guessing, dependence on workbook fields,
or special branches keyed on the presence of an adjustment.

## Adjustment surface (complete)
`co_stock_adjustments` is touched by exactly 6 modules: `co_stock_adjustments_store`
(owner), `co_stock_materializer`, `web/co_case_context`, `routers/co_stock`,
`co_stock_template`, and `scripts/fix_trului_unit`.

Only **two** adjustment fields ever reach logic: `opening_qty_override` and `used_qty`,
exclusively via `aggregate_by_lookup_key()` → `fold_baseline()`. Five callers of
`aggregate_by_lookup_key` (materializer refresh / refold_adjustment_lots /
refold_all_adjustments, co_case warm context, co-stock export) all fold-only. `fold_baseline`
writes only qty fields onto the snapshot:
`bcct_qty, opening_qty, available_qty, baseline_used_qty, used_qty, remaining_qty`.

The lock guard (`co_stock_ledger.record_sheet_lock`) and every read path
(`_calculate_stock_rows_from_snapshot`, `origin_source_context`, lot-history,
`co_stock_summary`) consume only the folded `remaining_qty` + the live ledger overlay
(`apply_used_qty`). **No workbook value/unit field drives any calculation or branch.** ✅

## Findings

### F1 — MEDIUM (real, open hole): no unit guard at import
This is the flip side of the principle. The fold is deliberately dumb and trusts
`opening_qty_override` as-is, but `unit_value` / `exchange_rate_to_vnd` on the lot come from
BCCT (per **BCCT** unit). When workbook unit ≠ BCCT unit, the fold silently produces a
wrong-unit opening → wrong `remaining_qty` (over-allocation risk in the lock guard) AND a
×1000 value error — with **zero warning**. The `unit` column *is* imported and stored
(`co_stock_template` → `upsert_batch`) but is **never compared** to the matching lot's BCCT
unit anywhere. This is exactly the bug that already shipped; it is only ever caught
reactively by `scripts/fix_trului_unit.py`. The door is still open for the next mismatched
workbook.
- **Fix:** the parked "import-time warning when adjustment unit ≠ BCCT unit" is the correct
  and *only* remaining systemic mitigation. Best placed in the import endpoint
  (`routers/co_stock.import_co_stock_workbook`) or `refold_adjustment_lots`, where both the
  workbook `unit` and the snapshot lot's BCCT `unit` are in hand. Surface as a non-blocking
  import warning + per-lot flag; do NOT auto-convert (keeps the fold dumb, per decision).
- Stays consistent with `fold_baseline` remaining dumb — this is a *door guard*, not logic.

### F2 — LOW: dead fold flags
`fold_baseline` writes `adjustment_applied` / `opening_qty_adjusted` into the persisted
payload, but nothing reads them (only the deprecated `apply_adjustments` tests assert on
them). Harmless metadata, not a logic dependency. Either drop them or wire to a UI "đã điều
chỉnh" badge — currently they are persisted noise.

### F3 — LOW: deprecated `apply_adjustments` + stale module docstring
`apply_adjustments` (read-time overlay that mixes adjustment override + used into a single
remaining) is the old anti-pattern. It is no longer in any app read path (only
`tests/test_co_stock_template.py` imports it). Keep deprecated, but:
- The module header docstring (`co_stock_adjustments_store.py:1-13`) still documents the OLD
  3-step apply-order ("apply_adjustments() optionally overrides available_qty and adds…").
  It is misleading vs the current fold model and should be rewritten to describe
  fold_baseline (materialize-time, qty-only) + ledger overlay (read-time).

### F4 — LOW (latent): wide stored-but-unused field surface
`co_stock_adjustments` persists `unit_price, taxable_unit_price, exchange_rate, hs_code,
goods_name, origin_country, unit, partner`. None are read into logic today — `list_for_client`
(the only accessor that returns them) has no external callers. This is latent risk: the
workbook's economic fields are sitting in the table inviting a future dev to "enrich"
calculations from them, which would re-violate the principle. Recommend a one-line guardrail
comment on the table/store marking these audit-trail-only, and (optional) a test asserting no
read path pulls adjustment value fields.

## Verified clean
- Calculate/origin hot path (`_calculate_stock_rows_from_snapshot`): folded snapshot +
  ledger only; no per-calc adjustment query, no unit logic.
- Lock guard (`record_sheet_lock`): reads folded `remaining_qty` only.
- Export / lot-history / co_case warm context: `fold_baseline` (idempotent) + `apply_used_qty`.
- `scripts/convert_co_stock.py`: pure transcription (column-position map, sums `used_qty`,
  merges `source_co_no`). No unit conversion or guessing.
- No branch anywhere keys on "an adjustment exists" (the flags in F2 are never read).
- No `/1000`, kg↔tonne, or unit-inference heuristic exists in `app/` runtime. The only mass
  conversion lives in the sanctioned data-repair script `fix_trului_unit.py`.

## Verdict
The 2026-06-06 decision is honored in all runtime logic: trừ-lùi is a qty-only folded
snapshot and never a logic variable. The single substantive gap is **F1** — the import path
does not validate workbook unit against BCCT unit, so a mismatched workbook can still
silently corrupt the snapshot exactly as before. F2–F4 are cleanup/latent-risk items.

## Pointers
- Memories: `trului-unit-mismatch-fold`, `co-stock-folded-remaining-model`.
- Key files: `app/co_stock_adjustments_store.py` (fold + deprecated overlay),
  `app/co_stock_materializer.py` (fold triggers), `app/co_stock_ledger.py` (guard + overlay),
  `app/routers/co_stock.py:258` (import — F1 fix site), `app/web/co_case_context.py:319-333`.
