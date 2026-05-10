# Notes for CO — substitute lookup now Bearer-aware

**Provider:** Data Hub  ·  **Consumers:** CO  ·  **Date:** 2026-05-13

Posted from Data Hub side in response to a CO blocker report:
> CO server-to-server gọi `GET /api/v1/clients/{c}/materials/{m}/substitutes`
> bị 401 với mọi Bearer token. Route dùng cookie-only auth.

## What changed in Data Hub

New mirror endpoint at the canonical sister-app prefix:

```
GET /v1/hub/clients/{client_id}/materials/{material_code}/substitutes
```

Same response shape as the existing `/api/v1/...` UI route. Bearer-auth
via the same `_require_token` helper used by every other `/v1/hub/*`
route — supports user JWT and service tokens.

The legacy cookie-only `/api/v1/clients/{c}/materials/{m}/substitutes`
stays as-is for the in-app catalog detail page.

## What CO needs to do

1. Switch the lookup URL from `/api/v1/...` to `/v1/hub/...`.
2. Send `Authorization: Bearer <token>` header.
3. Token must be:
   - In `api_auth_strict=true` (production): a valid Data Hub-issued JWT.
     Service token must carry `hub:read` in `scopes`.
   - In `api_auth_strict=false` (dev default): any non-empty bearer is
     accepted (legacy permissive mode). Use a real service token anyway
     so the same code path works in both environments.

## Query params (unchanged)

- `min_score` (float, default `0.5`) — drop pairs with combined_score below this.
- `include_rejected` (bool, default `false`) — include rejected pairs.
- `limit` (int, default `20`, max `100`).

## Response shape

```json
{
  "client_id": "johnson-vn",
  "material_a_code": "MFW0502-39",
  "count": 15,
  "items": [
    {
      "material_b_code": "MFW0502-02",
      "name": "MFW0502-02#&Thiết bị... (full goods_name)",
      "category": "tp",
      "hs_code": "95069100",
      "sources": ["embedding", "trigram"],
      "raw_scores": {"embedding": 0.9597, "trigram": 0.6154},
      "combined_score": 0.9718,
      "confirmed": false,
      "confirmed_at": null
    }
  ]
}
```

## Auth failure modes

- Missing Authorization header → `401 bearer token required`.
- Empty bearer (`Authorization: Bearer ` with no token) → `401 empty bearer token`.
- Service token without `hub:read` scope → `403 service token missing required scope: hub:read`.
- Service token with `client_ids` whitelist that excludes the requested
  `client_id` → `403 client not in service-account whitelist`.
- Strict mode + non-JWT bearer → `401 invalid token: ...`.

## Tests

`tests/test_substitute_api_v1.py` — 7 tests covering no-auth / service
token / scope / whitelist / min_score paths.

## Related

- Service-account JWT model: `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`.
- Mint a token: `uv run python scripts/mint_service_token.py create --name co --scopes hub:read,bom:propose --client-ids ... --created-by <admin>`.
