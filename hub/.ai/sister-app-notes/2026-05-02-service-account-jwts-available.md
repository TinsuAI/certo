# Notes for CO + BCQT — service-account JWTs available

**Provider:** Data Hub  ·  **Consumers:** CO, BCQT  ·  **Date:** 2026-05-02

Posted from Data Hub side. Each repo can adopt at its own pace; the
existing user-JWT path remains supported for now.

## What changed in Data Hub

New non-human identity model for `/v1/hub/*` callers. Same Ed25519
signing key + JWKS endpoint as user JWTs — signature verification is
identical; only the claim shape differs.

**What consumer-side verifiers MUST do for service tokens:**
- Inspect `claims["typ"]`. If `"service"`, **do not** attempt to
  construct a `User` from the claims (no `email`, `role`, `display_name`).
  The `sub` is `svc:<name>`, not a uuid.
- Treat `claims["scopes"]` and `claims["client_ids"]` as advisory only —
  Data Hub re-derives them from its own registry on every call. The token
  is *authentication*, the DB row is *authorization*.
- Accept that a service token may carry `client_ids=null` ("all clients
  for the granted scopes") — apply your own ACL on top if you need
  tighter restriction.

**Token shape:**
```json
{
  "iss": "http://localhost:8754",
  "sub": "svc:co",            // svc:<account name>
  "iat": 1714617600,
  "exp": 1717209600,           // 30d default
  "typ": "service",
  "name": "co",
  "scopes": ["hub:read", "bom:propose"],
  "client_ids": null,          // null = all clients; or ["growatt-vn", ...]
  "jti": "<uuid4 hex>"
}
```

**Scope mapping enforced in the API:**

| Endpoint | Required scope |
|---|---|
| `GET /v1/hub/*` (all reads — dncxs, bcct, bom, materials, code-mappings, etc.) | `hub:read` |
| `POST /v1/hub/products/{product_code}/bom/proposals` | `bom:propose` |

**Client whitelist:** if the token's `client_ids` is non-null, the API
rejects requests for clients outside the list with 403. Token issuer
should pass `client_ids=None` only when the service legitimately needs
multi-tenant access.

**Revocation:**
- Soft (entire account): `delete from hub.service_accounts where name = ?`
  via `scripts/mint_service_token.py delete --name <name>`. Verifier
  rejects every token for that account on its next call.
- Specific token (leak): `revoke-jti --jti <hex>` adds the jti to a
  blacklist. Verifier checks the blacklist before accepting.

## Why CO/BCQT should adopt

Today CO/BCQT carry a real **user**'s JWT (typically an admin) when
calling Data Hub APIs. Pain points:

1. User offboarding breaks the integration. Service tokens are
   independent of human accounts.
2. Audit trails record the user's id as the actor — looks like a human
   change in `bcct_row_history`.
3. The user's ACL is broader than what CO actually needs (CO only needs
   `bom:propose` + `hub:read` for its own clients). Service tokens
   carry only the minimum.
4. Required for Data Hub to safely flip `api_auth_strict=true` in
   production — that flag rejects legacy bearer-anything strings, and
   service callers need a real JWT identity.

## What CO needs to do (by ~2026-06-01 if convenient — no hard deadline)

1. Ask the Data Hub admin to mint a service token for CO:
   ```bash
   uv run python scripts/mint_service_token.py create \
     --name co --scopes hub:read,bom:propose \
     --client-ids growatt-vn,dke-vn,johnson-vn,do-thanh-vietnam-2614 \
     --description "CO production" \
     --created-by admin@data-hub.local
   ```
   Save the returned token securely (it cannot be re-displayed). The
   `--created-by` value is a free-form audit string (typically the admin's
   email); it's NOT a foreign key to a user table.
2. In CO `app/data_hub_client.py`, accept a `DATA_HUB_SERVICE_TOKEN`
   env var alongside the existing user-token mechanism. Pass it as
   `Authorization: Bearer <token>` for service-to-service calls.
3. Stop carrying a real user's JWT in cron/batch paths.
4. (Optional follow-up) If CO ever runs jobs across all agencies,
   request `client_ids=None` on the token; otherwise prefer the
   explicit whitelist.

**Token refresh:** there is no refresh flow. Tokens have a 30-day TTL
(default; configurable per-token via `--ttl-seconds`). Before expiry,
the Data Hub admin re-mints; CO updates its env var. No automated
rotation is planned for v1 — the token volume is tiny (~2 service
accounts) and ops handles re-mint manually. Don't build a refresh-token
flow that doesn't have a corresponding endpoint.

## What BCQT needs to do (whenever consumer-mode integration lands)

Same pattern, scopes = `["hub:read"]` (BCQT has no Data Hub writes
today). Use a separate account name (`bcqt`) so audit + revocation
are independent.

## Coexistence

Both user-JWT and service-JWT paths are supported simultaneously. CO
and BCQT can flip on their own schedule. Data Hub will not deprecate
the user-JWT path until both consumers have switched.

## Reference

- Data Hub design doc: `.ai/features/2026-05-02-service-account-jwts.md`
- Data Hub CLI: `scripts/mint_service_token.py`
- Migration: `db/migrations/020_service_accounts.sql`
- Token issuer: `app/jwt_issuer.py:make_service_token`
