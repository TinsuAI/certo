# Data Hub API Request: session-token-refresh

## Use Case
CO operators work inside a single case for long stretches — building the
substitute plan in the "Tìm NVL thay thế" modal, recalculating tồn, saving bảng
kê. The CO session is the Data Hub access token (JWT) stored in the
`co_data_hub_session` cookie. It is minted once at SSO callback with
`max_age = expires_in or 600` and never renewed while the operator works.

Prod symptom: roughly every ~10 minutes (the DH token lifetime) the session dies
mid-work. The next guarded `/clients/...` XHR is challenged; before the CO-side
fix it followed a 303 into the cross-origin SSO page and the browser threw
`TypeError: Failed to fetch` ("Mất kết nối máy chủ"), losing all client-side
substitute work. CO has already shipped the client-side half: guarded XHRs now
get a readable `401 {code:"session_expired"}` and a re-login prompt that
preserves the page. This request covers the **root cause** — so an actively
working operator is never forced to re-authenticate every ~10 minutes.

## Existing Endpoint Gap
Checked in `app/co_auth.py` / `app/routers/auth.py`:
- `GET {data_hub}/v1/auth/authorize` — full interactive SSO; requires a browser
  round-trip, cannot renew silently.
- `POST {data_hub_api}/v1/auth/exchange` — one-shot code→token exchange at login.
  Returns `access_token` + `expires_in`. **Open question for DH: does it also
  return a `refresh_token`?** Nothing in the CO code reads one today.
- `GET {issuer}/v1/auth/jwks` — verification keys only.

No endpoint lets CO renew a near-expiry access token without a new interactive
SSO authorize. There is also no confirmed short token TTL rationale — if the
~600s `expires_in` is just a default, a longer TTL is the cheapest partial fix.

## Proposed Contract
Preferred: a refresh endpoint (OAuth-style), so tokens stay short-lived but
renewable.

Method and path: `POST {data_hub_api}/v1/auth/refresh`

Query parameters: none

Request body:
```json
{ "refresh_token": "<opaque refresh token issued at exchange>" }
```

Response body:
```json
{
  "access_token": "<new DH JWT>",
  "expires_in": 600,
  "refresh_token": "<rotated refresh token, optional>"
}
```

Error cases:
- `400` malformed body (missing `refresh_token`).
- `401` refresh token expired / revoked / unknown → CO falls back to full SSO
  login (the current behavior).
- `403` refresh token valid but user no longer permitted.

Dependency: `POST /v1/auth/exchange` must return a `refresh_token` at login for
CO to store (httponly cookie, separate from the access-token cookie).

Alternative if refresh tokens are undesirable: a **silent authorize**
(`GET /v1/auth/authorize?...&prompt=none`) that returns a fresh code without user
interaction when the SSO session is still alive, which CO exchanges as today.
State the preferred option.

## Auth
Required scope: none beyond proof of the refresh token itself. Refresh must NOT
require the operator JWT (it is expired by definition at refresh time).

Client scoping rule: the new access token carries the same client claims as the
original; refresh must not broaden the visible-client set.

Token type: opaque refresh token (rotating preferred), bound to the user + SSO
session. Access token stays a short-lived EdDSA JWT verified via existing JWKS.

## Data Semantics
Source of truth: Data Hub SSO/identity service.

Precision requirements: n/a.

Pagination: n/a.

Idempotency: refresh is not idempotent if tokens rotate; a rotated refresh token
invalidates the previous one. CO must handle a rotation race (two in-flight
refreshes) by serializing refreshes and retrying the guarded call once.

Versioning or pinning: n/a.

## Tests Required In Data Hub
Provider tests:
- `exchange` returns a `refresh_token`.
- `refresh` with a valid refresh token returns a new, verifiable access token
  whose claims (sub, role, client claims) match the original.
- Rotated refresh token: old token is rejected after one use.

Negative tests:
- Expired / revoked / unknown refresh token → 401.
- Malformed body → 400.
- Refresh does not accept an access token in place of a refresh token.

Edge cases:
- Concurrent refresh with the same token (rotation race) → exactly one succeeds.
- Refresh after the user's client ACL changed → new token reflects the change.

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py` (or `app/co_auth.py` next to
`exchange_data_hub_sso_code`): `refresh_data_hub_session(refresh_token) -> dict`.

Call sites that will consume the adapter:
- A CO route, e.g. `POST /auth/refresh`, that the client calls before expiry
  (proactive keep-alive timer) or on catching `401 session_expired`, then
  re-issues the `co_data_hub_session` cookie via `set_session_cookie`.
- Optionally the `require_data_hub_auth` middleware to auto-refresh a near-expiry
  token server-side and set a fresh cookie on the response.

Consumer tests:
- Near-expiry token + valid refresh cookie → CO route returns 200 and sets a
  fresh `co_data_hub_session`.
- Invalid refresh → CO route returns `401 session_expired` (client shows the
  existing re-login prompt).

## Approval
Data Hub contract owner:

Approval date:

Data Hub commit:
