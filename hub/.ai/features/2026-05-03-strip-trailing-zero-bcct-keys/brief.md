# Feature: strip trailing `.0` from BCCT key fields

**Date:** 2026-05-03 (PM)
**Status:** shipped (uncommitted)
**Trigger:** Real-data API smoke from the previous feature surfaced
declaration_no values like `308449399330.0` and line_no `133.0`. Root
cause traced to `app/parsers/bcct.py:_cell_str` calling `str(v)` on
openpyxl float cells without first coercing integer-valued floats back
to int.

## Scope

- **Parser fix:** `_cell_str` now detects integer-valued floats and
  coerces to int before stringifying. Real decimals (e.g. `1.5`)
  survive untouched. Applies to every text-of-number BCCT field
  (`declaration_no`, `line_no`, `customs_code`, `internal_code`,
  `exporter_tax_code`, …).
- **Migration 024:** strips `.0` from existing
  `hub.bcct_rows.declaration_no`, `line_no`, and rebuilds
  `transaction_key = '{decl}-{line_no}'` from the cleaned values.
  Mirrors the cleanup into `hub.bcct_row_history`. Suppresses the
  history trigger for the duration so we don't write thousands of
  audit rows for a system-wide cleanup.

## Impact

| Table | Polluted rows before | After |
|---|---|---|
| `bcct_rows.declaration_no` | 5119 / 5126 | 0 |
| `bcct_rows.line_no` | 3631 / 5126 | 0 |
| `bcct_rows.transaction_key` | 5119 / 5126 | 0 |
| `bcct_row_history.transaction_key` | 435 / 22231 | 0 |

`transaction_key` is the PK of `hub.bcct_rows`; cleaning it ensures
re-uploads of the same Excel conflict-update existing rows instead of
inserting duplicates.

## Out of scope (one related bug worth flagging)

Spot check during the audit found `bcct_rows.currency` contains values
like `1864.0`, `2784.0`, …, not `USD` / `VND` / etc. That is a
separate **column-mapping** bug (the parser is matching the wrong
Excel column to `currency`), not a `.0` artefact. Cleaning it now
would mask the underlying bug. Tracked for a follow-up; out of scope
for this PR.

## Files changed

```
app/parsers/bcct.py                     _cell_str: int-coerce float
db/migrations/024_strip_trailing_zero_from_bcct_keys.sql   new
tests/test_parsers.py                   + 2 tests for _cell_str + roundtrip
tests/test_bcct_no_trailing_zero.py     new — 3 live-DB integrity checks
.ai/features/2026-05-03-strip-trailing-zero-bcct-keys/brief.md   new
.ai/sister-app-notes/2026-05-03-bcct-key-shape-cleanup.md   new
```

No UI surface — no `screenshots/`.

## Manual verification

```bash
curl -s "http://127.0.0.1:8754/v1/hub/bcct/invoice-matches?\
client_id=growatt-vn&invoice_no=GUS28826A131-3F&declaration_types=E42" \
  | jq '.items[0] | {declaration_no, line_no, transaction_key, item_code}'
```

Expected (post-fix):
```json
{
  "declaration_no": "308449399330",
  "line_no": "133",
  "transaction_key": "308449399330-133",
  "item_code": "SD00.0010600"
}
```

`item_code` `SD00.0010600` retains its real internal dot (this is the
customs-form code, not parser pollution).

## Done criteria

- [x] Migration applies cleanly; collision pre-flight returns 0.
- [x] Real-data smoke: every Growatt invoice-match row has clean keys.
- [x] Parser unit tests cover float-with-.0, real-decimal-preserved,
  None / "" edge cases.
- [x] Live-DB integrity tests assert `bcct_rows` + `bcct_row_history`
  have zero `.0` contamination — catches regressions if the parser
  fix is later reverted.
- [x] 350 passed, 15 skipped (was 345 → +5 new).

## Notes for sister apps

`transaction_key` shape changed permanently. CO + BCQT consumers that
cache a transaction_key locally (and might still hold values like
`308449399330.0-133.0`) will see stale-cache mismatches once. After
re-fetching from `/v1/hub/bcct/*`, those caches naturally rebuild.
See `.ai/sister-app-notes/2026-05-03-bcct-key-shape-cleanup.md`.
