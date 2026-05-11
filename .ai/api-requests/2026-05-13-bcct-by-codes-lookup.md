# Data Hub API Request: BCCT lookup by material codes

## Use Case

CO derives "tồn CO" (CO stock pool) from `BCCT direction=import` rows by
applying CO-side allocation_code + eligibility rules
(`app/source_store.py::co_stock_rows_from_bcct`). Today this requires
**full BCCT pagination** for the client because Data Hub `/v1/hub/bcct`
only filters by `client_id, year, direction, declaration_no`.

For Johnson with 65,846 BCCT rows, every CO flow that needs stock
(substitute modal, origin sheet calc, page render) re-paginates ~65
pages × ~400ms each ≈ **30 seconds** per fetch. CO-side cache (90s
TTL) helps repeats but the first call is unbearable.

The substitute modal in particular only needs stock for the ~20
candidate material codes returned by
`/v1/hub/clients/{c}/materials/{m}/substitutes`. CO doesn't need
stock for the other 65k unrelated rows.

## Existing Endpoint Gap

Existing endpoints checked:

- `GET /v1/hub/bcct?client_id=X&direction=import` — no `customs_code` /
  `item_code` filter. Confirmed by reading
  `data-hub/app/routes/api.py::api_list_bcct` (filters: client_id,
  year, direction, declaration_no only).
- `GET /v1/hub/bcct/invoice-matches` — invoice-keyed only, exports.
- `GET /v1/hub/clients/.../substitutes` — returns candidate metadata
  (score, name, hs_code) but no stock. Stock is per-customer
  CO-derived.
- No existing `/v1/hub/co-stock` endpoint (Data Hub `co_stock` is just
  a config schema, not a query).

## Proposed Contract

Method and path (Bearer-aware, service-token compatible):

```
GET /v1/hub/clients/{client_id}/bcct/by-codes
```

Query parameters:

- `codes` (string, required) — comma-separated list of customs codes
  (max 100). Match against `bcct_rows.customs_code` exact, OR against
  `bcct_rows.material_identity.bom_product_code` if Data Hub has the
  resolver pre-attached (optional enrichment).
- `direction` (string, optional) — `import` | `export`. CO calls with
  `direction=import` for stock; left optional for future read-only
  audits.
- `include_material_identity` (bool, default `false`) — same semantics
  as existing `/v1/hub/bcct`.
- `cursor`, `limit` (int, default 200, max 1000) — same pagination
  contract as existing list endpoint.

Response body — same row shape as `/v1/hub/bcct`:

```json
{
  "items": [
    {
      "client_id": "johnson-vn",
      "transaction_key": "108212187420-1",
      "line_no": "1",
      "declaration_no": "108212187420",
      "declaration_type": "E11",
      "direction": "import",
      "registration_date": "2026-05-06",
      "customs_code": "MAT-A",
      "goods_name": "...",
      "hs_code": "73182990",
      "quantity": 100.0,
      "unit": "PIECE",
      "unit_price": 12.34,
      "unit_price_nt": 0.5,
      "total_value": 1234.0,
      "currency_nt": "USD",
      "invoice_ref": "VNG...",
      "material_identity": { ... }    // when include_material_identity=true
    }
  ],
  "next_cursor": null,
  "total_estimate": 12
}
```

Error cases:

- 400 `missing codes` — empty `codes` param.
- 400 `too many codes` — > 100 codes in one request.
- 401 / 403 — same as existing `/v1/hub/*` routes.
- 404 unknown client.

## Auth

Required scope: `hub:read` (same as the rest of `/v1/hub/*`).

Client scoping rule: existing service-token whitelist enforces
`client_id` access — same as `/v1/hub/bcct`.

Token type: service-token Bearer JWT (typ='service'); user JWT also
accepted via `_require_token`.

## Data Semantics

Source of truth: `hub.bcct_rows` table.

Ordering: same as existing `/v1/hub/bcct` —
`order by registration_date desc nulls last, declaration_no, line_no`.

Codes matching: case-insensitive exact match against `customs_code`.
If Data Hub has time, also accept the resolved
`material_identity.bom_product_code` so CO can pass either.

Pagination: standard cursor + limit. CO will typically pass ≤ 50
codes and expect ≤ a few hundred rows back; pagination matters only
for codes with very long import history.

Idempotency: GET, idempotent.

## Tests Required In Data Hub

Provider tests:

- `codes` filter narrows to matching `customs_code` (single + multi).
- `direction` filter combines with `codes`.
- `include_material_identity=true` attaches resolver output.
- Empty `codes` → 400.
- More than 100 codes → 400.
- Service token without `hub:read` → 403.
- Cursor pagination round-trips.

Negative tests:

- Wrong client_id (whitelist mismatch) → 403.
- Unknown codes → 200 with empty items (not 404).

Edge cases:

- Codes with URL-unsafe characters → properly URL-decoded.
- Mixed-case input → matched case-insensitive.

## CO Consumer Plan

Adapter method to add in `app/data_hub_client.py`:

```python
def list_bcct_by_codes(
    self,
    client_id: str,
    codes: list[str],
    *,
    direction: str = "import",
    include_material_identity: bool = False,
) -> list[dict]:
    if not codes:
        return []
    return list(self._get_all(
        f"/v1/hub/clients/{hub_path_part(client_id)}/bcct/by-codes",
        {
            "codes": ",".join(codes[:100]),
            "direction": direction,
            "include_material_identity": "true" if include_material_identity else "false",
        },
    ))
```

Call sites that will consume the adapter:

- `app/main.py::co_case_origin_sheet_substitute_stock` (the lazy stock
  endpoint behind the substitute modal): replace
  `co_case_source_context_cached(...).stock_rows` with a single
  `list_bcct_by_codes(client_id, candidate_codes, direction="import")`
  call followed by the existing `co_stock_rows_from_bcct` derivation.
- Eventually: `co_case_source_context` itself (Data Hub mode) can stop
  full-paginating BCCT when it's only needed for invoice-match
  enrichment, or split into invoice-match + stock-by-codes paths.

Consumer tests:

- Mock the new adapter, verify substitute-stock endpoint returns
  `lots`, `total_remaining_qty`, `unit_price_min/max` per requested
  code.
- Confirm CO's CO-side `co_stock_rows_from_bcct` continues applying
  allocation/eligibility rules to the narrowed BCCT slice.

## Coordination

- CO will keep the existing 90s in-memory cache so a single substitute
  modal session stays cheap even after this lands.
- After CO migrates, write back-note in
  `~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-XX-co-bcct-by-codes-consumer-shipped.md`
  and remove the temporary `co_case_source_context_cached` warm-up
  path that pre-fetches the full catalog from `/origin` GET.

## Why Not Alternatives

- Data Hub computing `/v1/hub/co-stock` directly: would require Data
  Hub to know each client's `lot_policy` + `allocation_code` rules;
  these live in CO config (per Data Hub docstring at
  `routes/api.py:332`). Splitting "Data Hub returns BCCT slice; CO
  applies its own rules" keeps the logic where it belongs.
- CO disk cache (option A in the discussion): unblocks today but
  doesn't fix the architecture; substitutes-stock would still cost
  ~30s on cache miss / first run on a new machine. Disk cache can
  layer on top of this endpoint if needed.

## Approval

Awaiting Data Hub-side review. Per CO `CLAUDE.md`: CO will not
implement consumption against this endpoint until Data Hub ships
provider tests and bumps the contract changelog.
