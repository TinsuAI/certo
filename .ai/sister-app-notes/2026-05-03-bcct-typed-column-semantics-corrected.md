# Sister-app note: BCCT typed-column semantics corrected

**Date:** 2026-05-03 PM
**Audience:** CO repo (`barry-CO-main`) + BCQT-System (any consumer
that reads `/v1/hub/bcct/*`).
**Status:** Data Hub side merged.
**Data Hub feature brief:** `.ai/features/2026-05-03-bcct-typed-column-backfill/brief.md`

## What changed

A pre-2026-05-04 parser bug bound 6 BCCT typed columns to the wrong
Excel column (substring-match shadowing on aliases). All historical
rows were corrected by migration 025 backfilling from the verbatim
`payload` jsonb. The current parser already assigns correctly — this
is a one-time data correction, not an ongoing breaking change.

| Field | Before (wrong)                  | After (correct)                |
|-------|---------------------------------|--------------------------------|
| `currency`     | sequence numbers (`'1864.0'`, `'8.0'`) | `USD` / `VND` / `CNY` / `EUR` |
| `unit`         | package unit (`'PK'`, `'CT'`)   | goods unit (`'PIECES'`, `'KILO-GRAMMES'`, …) |
| `unit_2`       | empty                            | secondary goods unit            |
| `unit_price`   | raw Đơn giá (foreign cur)       | Đơn giá tính thuế (in VND)     |
| `total_value`  | Trị giá NT (foreign cur)        | Tổng trị giá (in VND)          |
| `line_no`      | workbook STT sequence            | STT hàng (line within decl)    |

`transaction_key` shape changed accordingly:

| Stage | transaction_key |
|-------|-----------------|
| Legacy | `308449399330.0-133.0` |
| After 024 (.0 cleanup) | `308449399330-133` |
| After 025 (semantic fix) | `308449399330-1` |

Where `1` = `STT hàng` (the line index within the customs declaration),
not `133` (an arbitrary workbook-wide row counter).

## What CO / BCQT need to do

- **Re-fetch any cached BCCT data** keyed by `transaction_key`,
  `line_no`, `currency`, `unit`, `unit_price`, or `total_value`. The
  values for the same physical row have changed.
- **Settlement totals** in BCQT that previously used `total_value`
  thinking it was VND-converted: the values were actually in foreign
  currency. Post-fix they are in VND. Existing settlement reports
  generated before this fix were arithmetically correct in their own
  numbers but referred to the wrong field name → re-run reports
  against the fresh data and confirm.
- **Currency-aware logic in CO**: previously `currency` was nonsense;
  any code branch that read it as 'USD' / 'VND' was effectively
  random. Now `currency` reflects the actual customs-declared
  currency.

## Why no API contract bump

The endpoint shape is unchanged — same JSON keys, same types. Only the
*values* are corrected. We treat this as a data fix, not an API
version bump. If your client persists snapshots and validates them
against historical data, you will need a one-time reconciliation.

## Coordination

- One-time cache flush + re-fetch on the consumer side.
- Re-running settlement / case-creation flows that depend on the
  affected fields will produce different numbers — that's expected
  and is the *correct* outcome.
- No PR needed unless your consumer caches affected fields.
