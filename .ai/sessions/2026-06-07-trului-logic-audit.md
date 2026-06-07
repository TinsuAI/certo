# Session: trừ-lùi "not a logic variable" audit

Date: 2026-06-07
Scope: read-only codebase audit (next-session priority #1 from the prior handoff). No code changed.

## Mandate
Principle (decided 2026-06-06): the trừ-lùi workbook is a stock SNAPSHOT to reconcile against,
not a driver of system logic. After the kg-vs-metric-ton bug (fixed as DATA via
`scripts/fix_trului_unit.py`, fold kept dumb), sweep for any *other* place adjustment data
leaks into logic — unit conversion/guessing, dependence on workbook fields, or branches keyed
on an adjustment existing.

## What was done
Traced the complete adjustment surface (6 modules touch `co_stock_adjustments`) and every
consumer of adjustment data. Recorded findings in
`.ai/audits/2026-06-07-trului-not-a-logic-variable-audit.md`.

## Verdict
Runtime logic is CLEAN. Only `opening_qty_override` + `used_qty` ever reach logic, via
`aggregate_by_lookup_key()` → `fold_baseline()` (qty-only). Lock guard
(`record_sheet_lock`) and all read paths (calculate, origin, export, lot-history, co_case
warm) consume only folded `remaining_qty` + live ledger overlay. No workbook value/unit field
drives any calculation or branch. No `/1000`/kg↔tonne heuristic in `app/` runtime (only in the
sanctioned `fix_trului_unit.py` data-repair script). `convert_co_stock.py` is pure
transcription.

## Findings
- **F1 (MEDIUM, real, OPEN):** import never compares workbook `unit` vs the lot's BCCT `unit`.
  Fold trusts `opening_qty_override` as-is while `unit_value` is per BCCT unit → a mismatched
  workbook silently corrupts the snapshot (over-allocation + ×1000 value), caught only
  reactively. Fix = non-blocking import-time warning at
  `routers/co_stock.import_co_stock_workbook` (do NOT auto-convert; fold stays dumb). This is
  the one remaining systemic gap and the concrete next action.
- **F2 (LOW):** `adjustment_applied` / `opening_qty_adjusted` flags written by `fold_baseline`
  but never read (tests-only). Dead metadata.
- **F3 (LOW):** deprecated `apply_adjustments` out of all read paths (tests-only); module
  docstring (`co_stock_adjustments_store.py:1-13`) still documents the old 3-step apply-order
  model — stale/misleading, rewrite to the fold model.
- **F4 (LOW, latent):** `co_stock_adjustments` stores 8 workbook value fields (unit_price,
  taxable_unit_price, exchange_rate, hs_code, goods_name, origin_country, unit, partner); none
  read into logic today (`list_for_client` has no external callers). Latent misuse risk.

## Decisions
- None changed. Confirmed the 2026-06-06 "fold stays dumb, fix data" decision holds across the
  whole codebase. F1 mitigation, if built, must be a door guard (warn), not a conversion.

## Open items / next
- F1 import unit-mismatch warning — not built (user deferred; "có thể làm sau").
- PROD + DEMO still need `scripts/fix_trului_unit.py johnson-vn --apply` run per the
  `trului-unit-mismatch-fold` memory (independent of this audit).
- Untracked/uncommitted docs accumulating in `.ai/` (this audit + session, prior handoffs).

## Pointers
- Audit doc: `.ai/audits/2026-06-07-trului-not-a-logic-variable-audit.md`.
- Memory updated: `trului-unit-mismatch-fold` (audit verdict + F1 appended).
- Key files: `app/co_stock_adjustments_store.py`, `app/co_stock_materializer.py`,
  `app/co_stock_ledger.py`, `app/routers/co_stock.py:258` (F1 site),
  `app/web/co_case_context.py:319-333`.
