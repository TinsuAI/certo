# Feature: BCCT invoice-matches market-hint fields

**Date:** 2026-05-03 (PM)
**Status:** shipped (uncommitted)
**Trigger:** Cross-repo API request from CO at
`barry-CO-main/.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md`.
CO needs market-country evidence on invoice lookup so the C/O case
creation flow can pre-populate form/agreement before operator confirms.

## Scope (additive)

Endpoint contract: `GET /v1/hub/bcct/invoice-matches`

- New query params:
  - `limit` (default 100, max 500 per spec; clamped server-side).
  - `cursor` (offset string, paired with response `next_cursor`).
  - `include_market_hint` (default `true`; `false` skips the computed hint).
- New per-item additive fields (raw evidence + computed hint):
  - `invoice_date`, `departure_date`, `incoterms`
  - `consignee_name`, `exporter_name`
  - `unloading_location` — read from BCCT payload key `Địa điểm dỡ hàng`
  - `destination_location_code`, `destination_location_name` — Vietnam-side
    bonded transport metadata, surfaced as raw evidence ONLY (never used
    as a market signal)
  - `market_hint` — `{country_code, country_name, source_field, source_value, confidence}`
    or `null`.
- Validation:
  - `400 missing_invoice_no` for empty / whitespace `invoice_no`.
  - `404 unknown_client` for `client_id` that is not in `hub.clients`.
  - `422 invalid_declaration_types` when filter contains tokens that
    don't match `^[A-Za-z0-9_]{1,16}$`.
- Stable sort: `registration_date desc nulls last, declaration_no asc,
  line_no::numeric asc, transaction_key asc`.

## Market hint rules (mirrored from spec, with one project decision)

- **High confidence**: `unloading_location` matches UN/LOCODE format
  `^[A-Z]{2}[A-Z0-9]{3}\b` and the country prefix is *not* `VN`.
- **Medium confidence**: country prefix is `VN`. Project decision —
  `VNZZZ` and similar mean "domestic bonded transfer", not a real
  export market. We surface VN with `medium` so CO operator confirms
  rather than auto-pre-populating Vietnam as the destination market.
  If CO prefers strict spec semantics ("any valid LOCODE → high"),
  we flip easily — adjust `app/markets.py:unloading_location_to_market_hint`.
- **Low confidence**: `unloading_location` present but does not match
  the LOCODE prefix. `country_code` and `country_name` are `null`,
  raw `source_value` preserved.
- **No hint** (`market_hint: null`): `unloading_location` empty / NULL.
- `consignee_name` is **not** used as a market signal (would require a
  reviewed mapping table; deferred until that table exists).
- `destination_location_*` fields are surfaced as raw evidence but
  never feed `market_hint`.

## Country code dictionary

Top ~50 markets in `app/markets.py:_ISO_3166_ALPHA2`. If a UN/LOCODE
country prefix isn't in the dict, the response still returns the code
with `country_name: null` (consumer renders the raw code). Extend the
dict additively as new markets appear.

## Storage

No migration. `Địa điểm dỡ hàng` reads through `payload->>` jsonb on
`hub.bcct_rows`. The endpoint queries by `(client_id, direction='export',
invoice_ref)` so the rowset is small enough that the json deref has no
measurable cost. If we later want to index/filter by unloading
country, we'll promote it to a typed column then.

## Files changed

```
app/markets.py                              new — dict + parser
app/routes/api.py                           expand /v1/hub/bcct/invoice-matches
tests/test_invoice_market_fields.py         new — 20 tests (provider + negative + helpers)
tests/test_read_api_auth.py                 update legacy test to subset-check
.ai/features/2026-05-03-bcct-invoice-market-fields/brief.md   new — this file
.ai/sister-app-notes/2026-05-03-bcct-invoice-market-fields-shipped.md   new
```

No UI surface, so no `screenshots/` folder.

## Manual verification

```bash
DATA_HUB_API_AUTH_DISABLED=1 uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload

# In another terminal, against the seed Growatt fixture (real data smoke)
curl -s "http://127.0.0.1:8754/v1/hub/bcct/invoice-matches?\
client_id=growatt-vn&invoice_no=GUS28826A131-3F&declaration_types=E42" | jq '.items[0]'
```

Expect: `market_hint.country_code == "US"`, `confidence == "high"`,
plus the additive fields populated.

## Done criteria

- [x] 20 new tests pass + 325 baseline still passes (345 total).
- [x] Existing legacy test still asserts the original 10-field subset
  (just relaxed to subset semantics).
- [x] All seven contract test cases from the request spec covered.
- [x] Negative cases (400 / 404 / 422) tested.
- [x] Pagination tested (limit + cursor).
- [x] Pure helper unit-tested.
- [ ] CO-side adapter update — **CO repo's job**, tracked in sister-app-note.

## Out of scope

- A `bcct_version_id` per row or response-level `source_version_id`. The
  spec mentions this as a follow-up; defer until CO actually needs
  versioned BCCT pinning.
- A `consignee_name → country` mapping table. Defer until reviewed
  mapping data exists.
- Promoting `unloading_location` to a typed column on `hub.bcct_rows`.
  Defer until query patterns require an index.
