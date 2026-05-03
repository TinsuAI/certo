# Data Hub API Request: BCCT Invoice Market Fields

## Use Case
CO case creation starts from an invoice number. After the operator enters an invoice, CO needs to identify the export market from reviewed BCCT export rows so it can suggest the C/O form and agreement before the operator manually chooses a market.

The current Growatt BCCT data shows the useful signal in `unloading_location` / raw `Địa điểm dỡ hàng`, for example:

- `USLAX - LOS ANGELES - CA` -> United States
- `INMAA - CHENNAI (EX MADRAS)` -> India
- `INNSA - NHAVA SHEVA` -> India

`destination_location_name` values such as `CANG LACH HUYEN HP` and `CANG NAM DINH VU` are Vietnam-side bonded transport destinations, not C/O destination markets, so CO must not use them as market evidence.

## Existing Endpoint Gap
Checked endpoint:

- `GET /v1/hub/bcct/invoice-matches?client_id=growatt-vn&invoice_no=GUS28826A131-3F&declaration_types=E42`

Current response items include product/declaration fields such as:

```json
{
  "declaration_no": "308449399330.0",
  "line_no": "133.0",
  "declaration_type": "E42",
  "item_code": "SD00.0010600",
  "description": "SD00.0010600#&Pin Lithium-ion...",
  "hs_code": "85076039",
  "quantity": 368.0,
  "unit": "CT",
  "invoice_ref": "GUS28826A131-3F",
  "transaction_key": "308449399330.0-133.0"
}
```

This is enough to list export products, but not enough to infer destination market. The richer BCCT list rows currently expose `consignee_name`, `destination_code`, `destination_name`, `invoice_date`, `departure_date`, and related fields, but the invoice-match endpoint does not include them. It also does not expose `unloading_location`, which is present in CO-local parsed BCCT state and is the best market signal.

## Proposed Contract
Method and path:

`GET /v1/hub/bcct/invoice-matches`

Query parameters:

- `client_id` required string. Must scope every result to one DNCX/client.
- `invoice_no` required string. Data Hub should match using the existing normalized invoice-token behavior.
- `declaration_types` optional comma-separated string. When supplied, only these declaration types are returned.
- `limit` optional integer, default `100`, max `500`.
- `cursor` optional string for pagination.
- `include_market_hint` optional boolean, default `true`.

Request body:

None.

Response body:

Additive fields on each item. Existing fields must remain stable.

```json
{
  "items": [
    {
      "declaration_no": "308449399330.0",
      "line_no": "133.0",
      "declaration_type": "E42",
      "item_code": "SD00.0010600",
      "description": "SD00.0010600#&Pin Lithium-ion...",
      "hs_code": "85076039",
      "quantity": 368.0,
      "unit": "CT",
      "invoice_ref": "GUS28826A131-3F",
      "transaction_key": "308449399330.0-133.0",
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
  ],
  "next_cursor": null,
  "total_estimate": 1
}
```

Market hint rules:

- Prefer `unloading_location` when it begins with a valid UN/LOCODE-style country prefix. Example: `USLAX` -> `US`, `INMAA` -> `IN`.
- Do not infer the importing market from `destination_location_code` or `destination_location_name`; those identify Vietnam-side customs/logistics locations in the observed data.
- If `unloading_location` is missing or ambiguous, return `market_hint: null` or `confidence: "low"` with the raw evidence fields still present.
- Do not infer from `consignee_name` unless Data Hub has an explicit, reviewed consignee-to-country mapping. If that mapping is used, set `source_field: "consignee_name"` and `confidence: "medium"` unless the mapping is reviewed.
- If one invoice has multiple rows with conflicting high-confidence market hints, return all rows and include an item-level hint; CO will require operator confirmation rather than silently selecting a market.

Error cases:

- `400 missing_invoice_no` when `invoice_no` is blank.
- `404 unknown_client` when `client_id` is not a known DNCX/client.
- `422 invalid_declaration_types` when declaration type filter is malformed.
- `401/403` according to Data Hub auth rules.

## Auth
Required scope:

- Read-only access: `hub:read`.

Client scoping rule:

- Returned rows must be limited to the requested `client_id`.
- User JWTs must only access clients allowed by their Data Hub ACL.
- Service tokens must include `hub:read` and be permitted for the requested client or all clients by existing Data Hub service-token policy.

Token type:

- User JWT or service token accepted by Data Hub read API policy.
- No mutating scope is needed.

## Data Semantics
Source of truth:

- Data Hub BCCT normalized rows remain the source of truth.
- `unloading_location` should come from the customs BCCT raw field `Địa điểm dỡ hàng` when available.
- `destination_location_code` and `destination_location_name` should remain available as raw logistics evidence, but they must not be labeled as importing market.

Precision requirements:

- Preserve raw text values exactly enough for audit and display.
- Country code should be ISO 3166-1 alpha-2 when Data Hub can infer it.
- `confidence` should be one of `high`, `medium`, `low`.

Pagination:

- Preserve current `items` envelope.
- Support `limit` and `cursor`; default `limit=100`, max `500`.
- Stable sort: declaration date, declaration number, numeric line number when possible, transaction key.

Idempotency:

- Read-only endpoint. Same query against unchanged Data Hub BCCT data must return the same rows and market hints.

Versioning or pinning:

- No endpoint version bump required if fields are additive.
- If Data Hub tracks BCCT source version IDs, include optional `bcct_version_id` per row or response-level `source_version_id` in a follow-up contract. Not required for this first market-hint request.

## Tests Required In Data Hub
Provider tests:

- `invoice-matches` returns `unloading_location`, `consignee_name`, `invoice_date`, `departure_date`, `incoterms`, `destination_location_code`, and `destination_location_name` for reviewed export rows.
- `USLAX - LOS ANGELES - CA` produces `market_hint.country_code == "US"` and `confidence == "high"`.
- `INMAA - CHENNAI (EX MADRAS)` and `INNSA - NHAVA SHEVA` produce `market_hint.country_code == "IN"` and `confidence == "high"`.
- Existing consumers still receive all currently documented fields unchanged.

Negative tests:

- Missing `invoice_no` returns `400`.
- Unknown `client_id` returns `404`.
- Rows for another client are never returned.
- `destination_location_name = "CANG LACH HUYEN HP"` does not produce Vietnam as market.

Edge cases:

- Multiple declaration rows for one invoice with the same market hint.
- Multiple declaration rows for one invoice with conflicting high-confidence country codes.
- Missing `unloading_location` but present `consignee_name`.
- `unloading_location` values that do not start with a valid country prefix.
- Invoice references containing multiple invoice tokens.

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`:

- Extend `DataHubClient.invoice_matches()` to preserve the added fields after approval.
- Add a small CO-side helper to derive the recommended market from item-level `market_hint`, requiring operator confirmation if there are zero or conflicting high-confidence hints.

Call sites that will consume the adapter:

- `app/portfolio.py` / `DataHubPortfolioService.co_case_source_context()`
- `app/main.py` C/O case creation and shipment context, where form lanes are currently derived from `case.destination_market`
- `app/templates/co_case.html` market picker preview

Consumer tests:

- C/O case with invoice `GUS28826A131-3F` receives a United States market hint and does not show origin demo when BCCT rows match.
- Invoice with India unloading location suggests India/Form AI only after Data Hub returns `market_hint.country_code == "IN"`.
- Conflicting hints display a manual market confirmation state rather than silently choosing one.
- Existing manual market selection still overrides the hint.

## Approval
Data Hub contract owner:

Pending.

Approval date:

Pending.

Data Hub commit:

Pending.
