# Data Hub API Request: Bearer-aware substitutes endpoint

> **Status: FULFILLED** — Data Hub shipped `GET /v1/hub/clients/{c}/materials/{m}/substitutes`
> on 2026-05-13 (commit ae3373b on Data Hub side). Bearer auth via service-token
> with scope `hub:read`. Response shape matches the legacy /api/v1 route.
> CO consumer migrated in `app/data_hub_client.py::DataHubClient.list_material_substitutes`
> on the same day. See `~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-13-substitute-api-bearer-available.md`
> for the live contract. Heuristic HS-prefix fallback in CO is retained as a
> safety net for `403 missing scope` and `401 invalid token` cases.

## Use Case

CO origin sheet substitution modal. When operator clicks a NVL cell in a bảng kê C/O, CO needs to fetch Data Hub's pre-computed substitute candidates (combined_score, raw_scores, sources, etc.) for the displayed material so the operator can pick a replacement and see expected LVC impact.

The operator triggers this from CO (port 8001). The lookup is server-to-server: CO calls Data Hub from its backend with the configured `DATA_HUB_SERVICE_TOKEN`. The browser does not call Data Hub directly.

## Existing Endpoint Gap

Existing endpoints checked:

- `GET /api/v1/clients/{client_id}/materials/{material_code}/substitutes` — has the data we need, **but only accepts `data_hub_session` cookie** (`auth.session.require_user`). Bearer tokens (user JWT, admin JWT, service token) all 401. Verified locally:

  ```
  GET /api/v1/clients/growatt-vn/materials/018.0645001/substitutes
    no Authorization        → 401
    Authorization: Bearer dev    → 401
    Authorization: Bearer admin  → 401
  GET /v1/hub/bcct?client_id=growatt-vn (Bearer dev)   → 200  (works)
  ```

- `GET /v1/hub/materials/{material_code}` (Bearer-allowed) returns the material itself, not substitute candidates.
- `GET /v1/hub/code-mappings` returns observed cross-mappings, not similarity-scored substitutes.

So CO cannot reach the `hub.substitute_candidates` table from server-to-server today.

## Proposed Contract

Method and path:

```
GET /v1/hub/clients/{client_id}/materials/{material_code}/substitutes
```

Place under the existing Bearer-aware `/v1/hub/...` namespace so the same `verify_token` (service-token) path applies.

Query parameters:

- `min_score` (float, default 0.5)
- `limit` (int, default 20, max 100)
- `include_rejected` (bool, default false)

Response body — same shape as the current `/api/v1/...` route returns:

```json
{
  "client_id": "growatt-vn",
  "material_a_code": "018.0645001",
  "count": 4,
  "items": [
    {
      "material_b_code": "018.0644700",
      "name": "...",
      "category": "npl",
      "hs_code": "...",
      "sources": ["hs_match", "trigram"],
      "raw_scores": {"hs": 1.0, "trigram": 0.83},
      "combined_score": 0.91,
      "confirmed": true,
      "confirmed_at": "2026-05-09T12:00:00Z"
    }
  ]
}
```

Error cases:

- 400 invalid client_id / material_code
- 401 invalid bearer
- 403 service token missing required scope
- 404 unknown client (not material — empty list)

## Auth

Required scope: `hub:read:substitutes` (new scope; or reuse `hub:read` if substitute candidates are considered general read data).

Client scoping rule: same as other `/v1/hub/...` endpoints — service-token whitelist enforces `client_id` access.

Token type: service-token (typ='service') Bearer JWT, OR a session-cookie user (so the existing UI route can be deprecated to this same path).

## Data Semantics

Source of truth: `hub.substitute_candidates` table (mig 047/048/049 + earlier substitute work).

Precision requirements: `combined_score` rounded to 4 decimals.

Pagination: not required initially; cap `limit` at 100.

Idempotency: GET, idempotent.

Versioning or pinning: not required.

## Tests Required In Data Hub

Provider tests:

- Service-token caller with valid scope → 200, items sorted by `combined_score` desc.
- Service-token caller without scope → 403.
- Unknown client → 404.
- Material not in catalog → 200 with empty items.
- `min_score` filter applied.
- `limit` capped at 100.

Negative tests:

- No bearer → 401.
- Bearer with wrong typ → 403.
- Service-token whitelist mismatch on `client_id` → 403.

Edge cases:

- `material_code` containing slash → URL-encoded path part.
- Material with zero substitutes → 200 with `count=0`.

## CO Consumer Plan

Adapter method to add in `app/data_hub_client.py`:

Already present: `DataHubClient.list_material_substitutes(client_id, material_code, ...)`. Switch path from `/api/v1/clients/{c}/materials/{m}/substitutes` to `/v1/hub/clients/{c}/materials/{m}/substitutes` once Data Hub ships. Remove the 401→service-token retry hack.

Call sites that will consume the adapter:

- `app/main.py::co_case_origin_sheet_substitute_candidates` (the substitute modal endpoint).

Consumer tests:

- Mock the adapter, verify CO endpoint enriches each candidate with `stock` (CO stock pool summary) and sorts per `optimization_mode`.
- Confirm 401 retry path is removed once Data Hub-side ships.

## Interim Workaround Until This Lands

CO's `/clients/{c}/co-case/{cid}/origin/sheet/{code}/substitute-candidates` endpoint will compute heuristic candidates locally when Data Hub returns 401:

1. Fetch the seed material from `/v1/hub/materials/{code}` to get its HS code and category.
2. Page through `/v1/hub/materials?client_id={c}` and select rows that share the seed's HS prefix (4-digit) and category, excluding the seed itself.
3. Score = HS-prefix overlap depth (0.5 for 4-digit, 0.7 for 6-digit, +0.2 if the candidate appears in CO stock).
4. Tag the response with `source: "co_heuristic"` and a banner so operator knows it's not the Data Hub similarity table.
5. Once Data Hub ships the Bearer-aware route, the heuristic is removed and the adapter targets the real endpoint.

## Coordination

Notify after CO migrates: write back-note in
`~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-XX-co-substitutes-bearer-consumer-shipped.md`.
