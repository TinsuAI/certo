# SSO design — Data Hub as identity issuer

**Date:** 2026-05-02 | Sprint B3. M9 deliverable #4.

Data Hub already owns user accounts + 4-role RBAC + per-client ACL. Wire SSO: BCQT-System and CO can verify a user's identity against Data Hub's JWT issuer instead of running their own login.

## Decisions

- **JWT, not OAuth2 / SAML.** Single-org deployment, all 3 apps under
  the same operator. OAuth2 adds redirect dance + state handling; SAML
  adds XML. JWT keeps the wire simple.
- **Asymmetric keys (Ed25519).** Issuer holds the private key; consumers
  verify via JWKS public keys. Secrets never travel between apps.
  Ed25519 over RSA: smaller signatures (88 bytes vs 256), faster verify,
  no padding-mode footguns. PyJWT supports it via `cryptography`.
- **Stateless verification at consumer.** Consumer validates signature +
  expiry locally; doesn't need to phone home for every request. Phone-home
  /validate endpoint exists for debug / one-shot identity reads.
- **Short-lived access token (10 min) + same session cookie.**
  No refresh tokens for MVP. Browser still uses the existing
  `data_hub_session` cookie for in-app login; the JWT layer is for
  cross-app calls. We'll revisit refresh/long-lived sessions when BCQT
  / CO actually deploy.
- **Same-domain deploy assumed for browser SSO.** All 3 apps under
  `*.data-hub.example` so the session cookie is shared via parent
  domain. Cross-domain SSO (different TLDs) is out of scope until
  someone actually requests it.
- **Service-to-service tokens (CO → Data Hub write API):** separate
  token type, signed with same key but with `aud=data-hub` and a
  service `sub` (e.g. `service:co-app`). Out of scope for B3 — covered
  in M9 deliverable #5.
- **Key rotation:** support multiple `kid`s in JWKS so we can publish
  a new key, wait for consumers to refetch, then sign with the new
  one. Storage: keys live on disk under `keys/`, gitignored, with the
  current `kid` recorded in `hub.app_settings`. For MVP, we ship one
  key; rotation infra is the table.

## Token claims

```json
{
  "iss": "https://data-hub.example",
  "sub": "u_31151f0497094109",     // user_id
  "iat": 1714615200,
  "exp": 1714615800,                // +10 minutes
  "email": "longle@xenowars.com",
  "role": "admin",                  // dev|admin|manager|staff
  "name": "Long Le"
}
```

Per-client ACL is NOT in the token — it's queried at the consumer side
against Data Hub's read API. Reasoning: ACL changes shouldn't require
re-issue. (If consumer is bandwidth-bound, we can add a `clients` array
with the user's accessible client_ids in v2.)

## Endpoints

- `POST /v1/auth/token` — body: `{email, password}` → `{access_token,
  expires_in, token_type: "Bearer"}`. Verifies password against
  `hub.users.password_hash` (argon2). 401 on bad creds. Same rate
  limit as the current login form.
- `GET /v1/auth/jwks` — public-key set in standard JWK format.
  Cache-Control: public, max-age 600. No auth required.
- `GET /v1/auth/validate` — bearer-required. Returns
  `{sub, email, role, name, exp}`. Used by consumers as a debug /
  one-shot validate. NOT meant for per-request validation —
  consumers should verify locally via JWKS.

## Consumer integration sketch

```python
# In BCQT-System or CO:
import jwt
import requests

JWKS = requests.get("https://data-hub.example/v1/auth/jwks").json()
PUBLIC_KEY = jwt.PyJWKClient(...)  # caches JWKS, refreshes on miss

def authenticate_request(token: str) -> dict:
    """Verify the token's signature against Data Hub's JWKS + claims."""
    signing_key = PUBLIC_KEY.get_signing_key_from_jwt(token).key
    return jwt.decode(
        token, signing_key,
        algorithms=["EdDSA"],
        audience=None,  # MVP doesn't enforce aud
        issuer="https://data-hub.example",
    )
```

## File layout

```
keys/
  ed25519.private.pem     # gitignored
  ed25519.public.pem      # gitignored

app/
  jwt_issuer.py           # load_keypair, make_token, verify_token
  routes/auth_api.py      # /v1/auth/* routes

db/migrations/
  017_sso.sql             # hub.app_settings keys for active_kid + iss

tests/
  test_jwt_issuer.py
```

## Risks + mitigations

- **Private key leak.** Stored on disk → use systemd unit's
  `ReadOnlyDirectories` + filesystem perms `0400 root:hub`. Document.
- **Key rotation downtime.** Mitigated by JWKS publishing both keys
  during rotation window. Operational SOP: 1) generate new key, 2)
  add to JWKS, 3) wait 1h for cache propagation, 4) flip
  `active_kid`, 5) wait for old tokens to expire (10min), 6) remove
  old key from JWKS.
- **Clock drift between apps.** Standard `leeway` in JWT verification
  (60s). Cap at 5min to limit replay window.
- **Replay attacks.** 10min `exp` is the primary defence. Adding a
  `jti` + Redis blocklist is overkill at MVP scale.
- **No refresh token = re-login every 10min for browser flow.**
  Compensated by the existing same-domain cookie staying valid for
  hours; JWT layer only kicks in for cross-app API calls. Document.

## Done criteria for B3

- POST /v1/auth/token returns a valid JWT for valid creds.
- GET /v1/auth/jwks returns parsable JWKS.
- GET /v1/auth/validate verifies the token + returns claims.
- Round-trip test: token from /token verifies against /jwks public key.
- Outsider key (different secret) does NOT verify.
- Tests pass.
