# Sister-app back-note — CO migrated to Bearer substitute endpoint

**From:** CO (`~/workspace/client/barry-CO-main`)
**To:** Data Hub team
**Date:** 2026-05-13

In response to Data Hub note `2026-05-13-substitute-api-bearer-available.md`.

## What CO did

- Switched `app/data_hub_client.py::DataHubClient.list_material_substitutes`
  from `/api/v1/clients/{c}/materials/{m}/substitutes` to
  `/v1/hub/clients/{c}/materials/{m}/substitutes`.
- Same `_get` path → service-token Bearer header is sent automatically.
- Updated CO Data Hub policy whitelist
  (`tests/test_data_hub_policy.py::APPROVED_DATA_HUB_ENDPOINTS`) to
  approve the new endpoint literal.
- Kept `403 missing scope` / `401 invalid token` returning
  `data_hub_unauthorized` so the substitute modal can fall back to the
  CO-side HS-prefix heuristic if the deployed service token lacks
  `hub:read`. The heuristic is informational only — a banner tells
  operators it is not the real similarity engine.

## Verified

```
GET /v1/hub/clients/johnson-vn/materials/MFW0502-39/substitutes?limit=3
Authorization: Bearer <dev|service token>
→ 200, count=3, items[].combined_score / raw_scores / sources present.
```

## Token requirement

Production CO needs a service token minted with `hub:read` scope and the
client-id whitelist that covers the customers CO operates on
(`growatt-vn`, `johnson-vn`, etc.). Local dev still works with any
non-empty bearer (`Bearer dev`).

## Tests

CO suite (`uv run pytest`) → 204 passed including the policy guardrails
(`test_raw_data_hub_api_calls_stay_in_adapter`, `test_data_hub_adapter_only_uses_approved_endpoints`).

## Follow-up

If Data Hub eventually deprecates the cookie-only `/api/v1/...` route,
CO is unaffected — we no longer call it.
