# Sister-app note: BCCT invoice-matches market-hint fields shipped

**Date:** 2026-05-03 PM
**Audience:** CO repo (`barry-CO-main`) — updates `app/data_hub_client.py`
+ `DataHubPortfolioService.co_case_source_context()` + the C/O case
creation flow.
**Status:** Data Hub side merged. CO side outstanding.
**Original request:** `barry-CO-main/.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md`
**Data Hub feature brief:** `.ai/features/2026-05-03-bcct-invoice-market-fields/brief.md`

## What CO can rely on now

`GET /v1/hub/bcct/invoice-matches` is now additive. Existing fields
unchanged. Each item has the following new fields (when data is
available; otherwise `null` / empty string):

```jsonc
{
  "invoice_date": "2026-04-18",
  "departure_date": "2026-04-21",
  "incoterms": "FOB",
  "consignee_name": "BASE POWER DEVELOPMENT, LLC",
  "exporter_name": "CONG TY TNHH NANG LUONG MOI GROWATT VIET NAM",
  "unloading_location": "USLAX - LOS ANGELES - CA",
  "destination_location_code": "03EES06",
  "destination_location_name": "CANG LACH HUYEN HP",
  "market_hint": {
    "country_code": "US",
    "country_name": "United States",
    "source_field": "unloading_location",
    "source_value": "USLAX - LOS ANGELES - CA",
    "confidence": "high"
  }
}
```

Response envelope: `{items, next_cursor, total_estimate}`. New query
params: `limit` (default 100, max 500), `cursor`, `include_market_hint`
(default `true`).

## Project decision worth flagging to CO

Spec said: "Prefer `unloading_location` when it begins with a valid
UN/LOCODE-style country prefix." Strict reading of that rule says any
`VN*` prefix → `country_code='VN'`, `confidence='high'`.

Real Growatt data has `VNZZZ - CONG TY TNHH ...` rows that are
domestic bonded transfers, not exports of *to Vietnam*. We chose to
return `country_code='VN'` with **`confidence='medium'`** instead of
`high`. The intent is that CO operator confirms market rather than
auto-pre-populating Vietnam.

If CO disagrees and prefers strict-spec (high), flip the branch in
`app/markets.py:unloading_location_to_market_hint` — single line:

```python
confidence = "medium" if code == "VN" else "high"
# → confidence = "high"
```

## What CO needs to do

1. **`app/data_hub_client.py`:** extend `DataHubClient.invoice_matches()`
   to surface the new fields after JSON parsing. Keep existing field
   names stable; add `market_hint` as `Optional[dict]`.
2. **C/O case creation flow** (likely `app/portfolio.py` /
   `DataHubPortfolioService.co_case_source_context()` and
   `app/main.py`): when a single high-confidence market hint is
   present across all returned rows, pre-fill the form/agreement
   selector. When multiple high-confidence hints conflict, render the
   manual market picker without a default.
3. **`app/templates/co_case.html`:** market-picker preview should show
   the source evidence (`source_value` + `source_field`) so the
   operator sees *why* a market was suggested.
4. **Tests** (CO side):
   - C/O case for invoice `GUS28826A131-3F` receives a US market hint.
   - India-unloading invoice suggests India + Form AI only after Data
     Hub returns `country_code == "IN"`.
   - Conflicting hints render the manual confirmation state.
   - Existing manual market selection still overrides any hint.

## Auth

Same as before: `hub:read` scope (user JWT or service token). When
operating against a dev Data Hub with `DATA_HUB_API_AUTH_DISABLED=1`,
no bearer is required (dev only).

## Pending coordination

- CO repo PR linking back to this note + the contract spec file.
- Once CO ships, mark "Approval" section of
  `barry-CO-main/.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md`
  with the Data Hub commit hash + approval date.
