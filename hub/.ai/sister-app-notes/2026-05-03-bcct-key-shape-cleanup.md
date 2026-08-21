# Sister-app note: BCCT key shape cleanup

**Date:** 2026-05-03 PM
**Audience:** CO repo (`barry-CO-main`) + BCQT-System (any consumer
that reads `/v1/hub/bcct/*`).
**Status:** Data Hub side merged.
**Data Hub feature brief:** `.ai/features/2026-05-03-strip-trailing-zero-bcct-keys/brief.md`

## What changed

Historical BCCT data had `declaration_no = "308449399330.0"` and
`line_no = "133.0"` (parser bug — openpyxl returns numeric cells as
float, parser stringified directly). `transaction_key` is built from
those, so it inherited the `.0` suffix on both ends:
`"308449399330.0-133.0"`.

Migration 024 stripped `.0` everywhere in `hub.bcct_rows` +
`hub.bcct_row_history`. The parser was patched
(`app/parsers/bcct.py:_cell_str`) so future uploads land clean.

## Effect on consumers

`transaction_key` shape changed permanently for the same physical
record. Example for the same Growatt row:

| Before | After |
|---|---|
| `308449399330.0-133.0` | `308449399330-133` |

Any consumer cache that pinned a transaction_key value will see a
stale-cache mismatch once. No data loss — the underlying record is
the same.

## What CO / BCQT need to do

- **No code change required** if you treat transaction_key as opaque
  and always re-fetch from the API.
- **One-time cache flush** if you persist transaction_key to local
  storage:
  - CO `data_hub_client.py` cache
  - BCQT per-project SQLite `data_files` / pipeline state
- After flush, the next API fetch hands back the cleaned form and
  the cache rebuilds naturally.

`declaration_no` and `line_no` shape changed similarly. Same
mitigation: re-fetch.

## Confirmation that other fields are fine

- `customs_code`, `internal_code`, `hs_code`, `exporter_tax_code`,
  `invoice_ref`: not contaminated. Excel had them as text already.
- `currency`: looks polluted (`'1864.0'` etc.) but that is a separate
  **column-mapping** bug — the parser is matching `currency` to a
  numeric column it shouldn't. Out of scope for this fix; tracked
  for a follow-up. Don't auto-clean values you don't expect to be
  numeric.

## Coordination

No PR needed on sister apps unless they cache. If you do cache,
schedule a flush; otherwise no action.
