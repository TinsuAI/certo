# DH → CO: refresh tokens available (silent access-token renewal)

**Date:** 2026-07-10 · **From:** Data Hub (mig 088, 089) · **To:** CO (`barry-CO-main`)
**Related:** `docs/API_CONTRACT.md` → Auth, `docs/API_CHANGELOG.md` → 2026-07-10 entry.

## Decision: refresh tokens, not `prompt=none`

CO asked for either. We built refresh tokens and did **not** add `prompt=none`.

The deciding fact is the Data Hub session cookie: `data_hub_session` is
`SameSite=Lax` (`app/auth/session.py`). A browser sends a Lax cookie only on
top-level navigations, so a silent `/authorize` from CO — a cross-site `fetch`,
an XHR, or a hidden iframe — would arrive at Data Hub **without** the SSO
cookie and be indistinguishable from a logged-out operator. Making it work
means `SameSite=None`, which weakens every Data Hub session to buy a renewal
path that still dies when the SSO cookie expires. The only `prompt=none` shape
that works today is a full top-level redirect, which is exactly the in-page
state loss CO is trying to avoid on the substitute-material plan.

A refresh token is a server-to-server call from CO's backend. No cookie, no
navigation, no SPA state loss. That is the right tool here.

## Answers to CO's open questions

1. **Does `/v1/auth/exchange` return a `refresh_token` today?** It did not.
   It does now.
2. **Access-token `expires_in`?** 600s, confirmed. Read from
   `hub.app_settings.sso_token_ttl_seconds` (default 600). Unchanged — the fix
   does not lengthen it.
3. **SSO session lifetime?** 14 days absolute (`SESSION_TTL_HOURS = 24 * 14`),
   set at login and **not** slid — `lookup_session` bumps `last_seen_at` only.
   Cookie `max-age` matches.
4. **`prompt=none`?** Not supported, and not recommended. See above.
5. **Recommendation + TTL.** Refresh tokens. Sliding **12h idle** window,
   extended on every refresh, under a hard **7d absolute ceiling** from first
   issue, itself capped by the 14d SSO session.

Why that shape: 12h idle covers a full shift, so a continuously-working
operator never re-logs; an abandoned workstation stops renewing overnight. The
7d ceiling bounds a stolen token that is rotated forever. Both are tunable in
`hub.app_settings` without a deploy: `sso_refresh_idle_ttl_seconds`,
`sso_refresh_absolute_ttl_seconds`, `sso_refresh_reuse_grace_seconds`.

## Contract

`POST /v1/auth/refresh`, body `{"refresh_token": "<opaque>"}`. No bearer. The
refresh token is the proof. Response is the same shape as `/exchange`.

- **Opaque.** Not a JWT. Never decode it. An access token passed in the
  `refresh_token` field is rejected on shape before it reaches the store.
- **Rotating.** The presented token is spent; its replacement comes back in the
  response. Persist the new one before the next call.
- **One winner.** Concurrent refreshes with the same token → exactly one `200`,
  the rest `401`. Enforced by a single-use `UPDATE ... WHERE used_at IS NULL`
  under the row lock, so it holds across workers and processes. CO's plan to
  serialize refreshes and retry the guarded call once is correct.
- **Replay revokes the family.** Re-presenting a token spent more than 30s ago
  revokes its whole lineage → full SSO login. Inside 30s it is treated as a
  benign race (401, family intact), which is what a lost race or a retried
  timeout looks like.
- **Scope never broadens.** Same `sub`, same `role`, same client scope as the
  original token. ACL revocations land on the next refresh; ACL *grants* do
  not — widening needs a fresh `/authorize` (RFC 6749 §6). A role promotion is
  likewise frozen until re-login; a demotion lands immediately.
- **Bound to the SSO session.** Data Hub logout revokes the refresh tokens
  minted from that session, so CO's silent renewal stops with it.

Errors: `400` missing/blank `refresh_token`; `401` unknown / expired / revoked
/ spent token, or dead SSO session → fall back to interactive SSO; `403` token
valid but the user is deactivated → retry will not help. Bodies are the usual
`{"detail": "..."}`.

## Keep-alive timing

Access token lives 600s. `verify_token` allows 60s leeway. Refresh at
**~T-120s** (i.e. every ~480s). Do not refresh more often than necessary —
each refresh rotates, and a rotation storm widens the window for a race.

## Nothing to migrate

Additive. CO keeps working untouched until it opts in. `exchange` gained one
field; the access token, its claims, and JWKS are unchanged.

## Verified

Live server on `:8754`, `--workers 4`, EdDSA verified offline against
`/v1/auth/jwks` via `PyJWKClient` — the same path CO uses. Exchange returns a
refresh token; refresh returns a JWKS-verifiable access token whose claims
match the original; rotation, replay, expiry, revocation, session-logout, ACL
narrowing, and 8-way concurrent refresh all behave as documented.
34 tests in `tests/test_sso_refresh.py`.

## Also fixed in this shipment: `/exchange` is now multi-worker safe (mig 089)

`/v1/auth/exchange` used to look the one-time SSO `code` up in a **per-process
in-memory dict** (`_SSO_CODES`). With more than one uvicorn worker, `/authorize`
could mint the code on worker A while CO's `/exchange` POST landed on worker B →
spurious `401 invalid or expired code`. Measured before the fix: **2 failures in
12 attempts** at `--workers 4`.

Production never saw it — the Docker image runs `--workers 1`. But
`deploy/systemd/data-hub.service` uses `--workers 2` and `CLAUDE.md` tells
developers to run `--workers 4`, so both of those shapes were affected, and any
future scale-out would have been.

Codes now live in `hub.sso_codes`, hashed, with the same single-use atomic
consume as refresh tokens. After the fix: **24/24** exchanges succeed at
`--workers 4`, and six concurrent exchanges of one code across workers produce
exactly one `200`. A `redirect_uri` mismatch still leaves the code spendable
(unchanged behaviour), and Data Hub logout now also invalidates any outstanding
code minted from that session.

No CO action. The contract did not change — the endpoint just stopped failing
intermittently.
