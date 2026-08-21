# Feature: backfill 6 mis-claimed BCCT typed columns

**Date:** 2026-05-03 (PM)
**Status:** shipped (uncommitted)
**Trigger:** Audit during the previous `.0` cleanup found
`hub.bcct_rows.currency` storing values like `'1864.0'`, `'2784.0'` —
not currencies. Cross-checking each typed column against the raw
`payload` jsonb (which preserves the original Excel header→value map
verbatim) surfaced 6 mis-claimed columns from the legacy parser.

## Audit summary

Pre-2026-05-04 BCCT parser used substring matching in `index_headers`
together with short aliases (`"đvt"`, `"tt"`, `"đơn giá"`, `"trị giá"`)
that incidentally matched longer customs headers earlier in the
column order. Result on real Growatt uploads:

| Typed column   | Bound to (wrong)                | Should bind to              | Mismatch |
|----------------|---------------------------------|-----------------------------|----------|
| `currency`     | `STT` (workbook seq)            | `Đơn vị tiền tệ`            | 5119/5125 |
| `unit`         | `Mã ĐVT kiện` (package unit)    | `Đơn vị tính`               | 5118/5125 |
| `unit_2`       | (nothing)                       | `Đơn vị tính 2`             | 5125/5125 |
| `unit_price`   | `Đơn giá` (raw, pre-FX)         | `Đơn giá tính thuế`         | 4195/5125 |
| `total_value`  | `Trị giá NT` (foreign currency) | `Tổng trị giá` (in VND)     | 4194/5125 |
| `line_no`      | `STT` (workbook seq)            | `STT hàng` (line in decl)   | 5115/5125 |

Substring matching was removed in commit `338be91` ("Phase 1 parser
bug fixes") and ALIASES expanded in `365bfed` ("stage A+B"); the
current parser assigns these correctly. This migration backfills the
legacy rows from `payload` jsonb (no re-parse needed — payload is
the lossless source-of-truth).

## Scope

- **Migration 025** backfills the 6 columns from `payload` keys.
- **`line_no` rebuild** participates in the PK
  `(client_id, year, transaction_key, line_no)`. To avoid transient
  collisions during the in-place UPDATE, the migration drops the PK,
  rewrites all rows, then recreates it. Pre-flight verifies the final
  state has no duplicate `(client_id, year, declaration_no, STT hàng)`
  tuples (0 collisions in current data).
- **`transaction_key` rebuild** to `'{declaration_no}-{cleaned_STT_hàng}'`
  so consumers see a meaningful line index.
- **`bcct_row_history`** mirror update for query consistency.
- **No parser change** — current parser is already correct (verified
  by tracing `index_headers` output against the real customs `.xls`).

## Impact on `transaction_key` shape

The shape change goes beyond migration 024 (which only stripped `.0`):

| Stage | transaction_key | line_no |
|-------|----------------|---------|
| Original (legacy parser) | `308449399330.0-133.0` | `133.0` |
| After migration 024 | `308449399330-133` | `133` |
| After migration 025 | `308449399330-1` | `1` |

The legacy `133` was the workbook-wide STT (sequence number); `1` is
the actual `STT hàng` (line within declaration), which is what CO and
BCQT need for case creation and settlement.

## Files changed

```
db/migrations/025_backfill_misclaimed_typed_columns.sql   new
tests/test_invoice_market_fields.py     fixture teardown also flushes history
.ai/features/2026-05-03-bcct-typed-column-backfill/brief.md   new
.ai/sister-app-notes/2026-05-03-bcct-typed-column-semantics-corrected.md   new
```

No parser change. No new tests beyond verifying the existing
integrity tests still hold (`test_bcct_no_trailing_zero.py` covers
no `.0` pollution in keys; the audit script in this brief was the
ad-hoc proof of correctness for the value backfill).

## Manual verification

```bash
curl -s "http://127.0.0.1:8754/v1/hub/bcct/invoice-matches?\
client_id=growatt-vn&invoice_no=GUS28826A131-3F&declaration_types=E42" \
  | jq '.items[0] | {declaration_no, line_no, transaction_key, unit, market_hint}'
```

Expected (post-migration 025):
```json
{
  "declaration_no": "308449399330",
  "line_no": "1",
  "transaction_key": "308449399330-1",
  "unit": "PIECES",
  "market_hint": { "country_code": "US", "confidence": "high", ... }
}
```

Distinct currencies post-fix: `CNY, EUR, USD, VND` (was 3046 sequence
numbers before). Distinct units: `PIECES, KILO-GRAMMES, METRES, SETS,
LITRES, …` (was `PK, CT, PP, …` package-unit values before).

## Done criteria

- [x] Migration 025 applies cleanly; 0 PK collisions in pre-flight.
- [x] Real-data audit: 0 mismatches across all 6 columns vs payload truth.
- [x] API smoke shows clean shape for declaration `308449399330`.
- [x] 350 tests pass, 15 skipped (no regression).
- [x] `bcct_row_history` mirrors the cleanup for joinable rows.

## Out of scope

- A typed column for `unloading_location`. Still read from
  `payload->>'Địa điểm dỡ hàng'` per the previous brief — index/filter
  pattern hasn't justified promotion yet.
- Re-parsing the original .xls files. Backfill from `payload` is
  faster, lossless, and avoids re-running the LLM-confirmed mapping
  flow (which has its own cache layer).
