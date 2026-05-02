# Service-Account JWTs (Discovery + Design)

**Date:** 2026-05-02
**Status:** Design — not yet implemented
**Why now:** Blocks `api_auth_strict=true` promotion. Removes "user JWTs in cron jobs" anti-pattern. Lets sister apps (CO, BCQT) call Data Hub APIs with a non-human identity that survives user offboarding.

## Current state (verified by reading code)

- `app/jwt_issuer.py` — Ed25519 issuer + verifier; kid-rotation friendly. `make_token()` issues user JWTs with claims (`sub`, `iss`, `exp`, `iat`, `email`, `role`, `name`).
- `app/auth/permissions.py` — `can_view_client` / `can_edit_client` / `can_edit_client_config` keyed on `User.role` ∈ {dev, admin, manager, staff} + per-client tables (`hub.user_managed_clients`, `hub.user_client_access`).
- `app/routes/api.py:48` — `_require_token()` accepts JWT; falls back to permissive bearer-anything when `api_auth_strict=false`.
- `app/routes/api.py:78` — `_require_jwt_claims()` strict JWT only. Used for the only mutating endpoint today: `POST /products/{product_code:path}/bom/proposals` (line 612).
- ACL functions build `User` from `claims["sub"]` (a uuid). For service tokens, `claims["sub"]` will be `svc:co` etc — no row in `user_managed_clients` / `user_client_access`, so `can_view_client` would return False unless `role in ("dev", "admin")`. Need a branch.

## Design

### Schema (migration `020_service_accounts.sql`)

```sql
create table hub.service_accounts (
  name           text primary key,            -- 'co', 'bcqt'; token sub becomes 'svc:co'
  description    text not null default '',
  scopes         text[] not null default '{}',
                                              -- ['hub:read', 'bom:propose', 'bcct:write']
  client_ids     text[],                      -- null = all clients; array = whitelist
  created_at     timestamptz not null default now(),
  created_by     text not null,               -- user_id of admin who created
  last_used_at   timestamptz                  -- updated on successful verify
);

-- jti blacklist for emergency revocation between mint and natural expiry.
-- Service tokens are 30d default; if a token leaks before expiry, add its
-- jti here to invalidate immediately. GC after token's exp passes.
create table hub.revoked_service_tokens (
  jti        text primary key,
  revoked_at timestamptz not null default now(),
  revoked_by text not null,
  reason     text not null default ''
);
```

**Why no `revoked_at` column on service_accounts itself:** simplest revocation = `delete from service_accounts where name=?`. The verifier looks up by `sub` suffix on every call. Deleting the row → next verify fails. The `revoked_service_tokens` table is for the rare case where a specific token leaked but the service account itself is still in use.

### JWT shape

```json
{
  "iss": "http://localhost:8754",
  "sub": "svc:co",
  "iat": 1714617600,
  "exp": 1717209600,
  "typ": "service",
  "name": "co",
  "scopes": ["hub:read", "bom:propose"],
  "client_ids": null,
  "jti": "<uuid4>"
}
```

`typ` claim (not header `typ` — that stays `JWT`) marks this as a service token. Verifier branches on it.

### Issuer (`app/jwt_issuer.py`)

```python
def make_service_token(
    *,
    name: str,
    scopes: list[str],
    client_ids: list[str] | None,
    ttl_seconds: int | None = None,
) -> dict:
    """Mint a long-TTL token for a service account.

    Same signing key + kid as user tokens — consumers verify the same way.
    Default TTL: 30 days (configurable via `service_token_ttl_seconds`).
    """
```

### Verifier (`app/jwt_issuer.py`)

`verify_token` extended: after standard decode, if `claims["typ"] == "service"`:
1. Check `claims["jti"]` not in `hub.revoked_service_tokens`.
2. Check `claims["name"]` exists in `hub.service_accounts`.
3. Update `last_used_at`.
4. Return claims.

If any check fails → raise `jwt.InvalidTokenError`.

### API ACL branching (`app/routes/api.py`)

New helper:

```python
def _require_scope(claims: dict | None, scope: str) -> None:
    """No-op for human JWTs (their role grants implicit scope).
    For service JWTs, require `scope` to be in claims['scopes']."""

def _require_can_view_client(claims, client_id):
    if claims is None: return
    if claims.get("typ") == "service":
        wl = claims.get("client_ids")
        if wl is not None and client_id not in wl:
            raise HTTPException(403, "client not in service-account whitelist")
        return
    # existing user-based ACL unchanged
    ...
```

Per-endpoint scope mapping (added to existing routes):

| Endpoint | Required scope (service tokens only) |
|---|---|
| `GET /v1/hub/*` (all reads) | `hub:read` |
| `POST /v1/hub/products/{product_code:path}/bom/proposals` | `bom:propose` |

### Bootstrap (CLI, no admin UI in v1)

`scripts/mint_service_token.py`:

```bash
uv run python scripts/mint_service_token.py create \
  --name co --scopes hub:read,bom:propose --description "CO production"
# Prints token to stdout ONCE. User responsible for storing.

uv run python scripts/mint_service_token.py list

uv run python scripts/mint_service_token.py delete --name co

uv run python scripts/mint_service_token.py revoke-jti --jti <uuid> --reason "leak suspected"
```

Admin UI deferred to follow-up. CLI is enough for the small set (CO + BCQT + maybe future cron jobs).

### Cross-repo coordination

After merge:
1. Sister-app note `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md` for CO + BCQT, instructing them to:
   - Stop using user JWTs in service-to-service calls.
   - Accept `DATA_HUB_SERVICE_TOKEN` env var; pass as Bearer.
2. CO `app/data_hub_client.py` change: read env var, pass on every call.
3. BCQT change: same pattern when its consumer-mode integration lands.

## Tests required

1. **Migration**: `020_service_accounts.sql` applies cleanly + idempotent on re-run.
2. **Issuer**: `make_service_token('co', scopes=['bom:propose'], client_ids=None)` produces token with expected claims (`typ=service`, `sub=svc:co`, `name=co`, `scopes=[...]`, `jti` is uuid4-shaped, `exp` ≈ now + 30d).
3. **Verifier happy path**: token verifies + `last_used_at` updated.
4. **Verifier — service account deleted**: token rejected.
5. **Verifier — jti revoked**: token rejected.
6. **API auth — scope enforcement**:
   - Service token with no `bom:propose` scope hits BOM proposal POST → 403.
   - Service token with `bom:propose` → 200.
7. **API auth — client whitelist**:
   - Service token with `client_ids=['growatt-vn']` calls `GET /dncxs/dke-vn` → 403.
   - Same token calls `GET /dncxs/growatt-vn` → 200.
   - Service token with `client_ids=null` calls any client → 200.
8. **CLI smoke**: create → list → mint → verify → delete cycle works.

## Out of scope (explicit)

- Admin UI — CLI is enough for ~2 service accounts.
- Audit GUC integration for service writes — would matter for a future BCCT write endpoint, but BOM proposals don't use the audit GUC today. Defer.
- Token refresh / rotation flow — TTL is 30d, ops re-mints when it expires.
- Per-scope rate limiting — not a problem at current scale.

## Done criteria

- All tests above pass.
- `_require_jwt_claims` on the BOM proposal endpoint accepts a service token with `bom:propose` scope.
- `api_auth_strict=true` works for service-account callers (the original blocker).
- Sister-app note posted.
- BACKLOG entry for "Service-account JWTs" removed; "API auth strict promotion" updated to note the blocker is unblocked.

## Risk

- **Token theft.** A leaked 30d service token is a longer compromise window than a 10min user token. Mitigations: `revoked_service_tokens` blacklist for fast revoke; future improvement: short-TTL access tokens via OAuth2 client_credentials flow.
- **ACL drift.** A service token with `client_ids=null` is effectively god-mode for its scopes. Mint with explicit `client_ids` whenever possible.
- **Cross-app coordination lag.** CO/BCQT may not pick up service tokens for weeks; meanwhile they continue using user tokens. Coexistence is fine — both code paths supported.
