# DH-side build prompt — renewable session so CO operators aren't forced to re-login mid-work

Hand this prompt to the Data Hub AI agent / dev. It is self-contained (does not
require the CO repo). This is a **session-lifetime** problem in production: the
CO (certificate-of-origin) service holds a DH access token that expires in
~10 minutes and there is no way to renew it without a full interactive SSO
round-trip, so operators get forced back to login every ~10 minutes and lose
in-progress work. Add a silent-renewal path.

---

```
You are working in the Data Hub codebase. You provide SSO + JWT auth for the CO (certificate-of-origin) service, today via:

  GET  /v1/auth/authorize?redirect_uri=...&state=...   -> interactive SSO, redirects back with ?code=...
  POST /v1/auth/exchange   { code, redirect_uri }      -> { access_token, expires_in }   (code -> token)
  GET  /v1/auth/jwks                                    -> EdDSA verification keys

The access_token is a short-lived EdDSA JWT (observed exp ~600s / 10 min). CO stores it in an httponly cookie, minted ONCE at the exchange callback, and never renewed.

## Problem (production)
There is no way to renew the token WITHOUT sending the operator back through interactive /v1/auth/authorize. So every ~10 minutes, mid-work, the operator's next API call is unauthenticated and CO must bounce them to SSO. On CO's single-page flows (e.g. building a substitute-material plan) this interrupts active work. We need the access token to keep expiring quickly (good for security) but be renewable SILENTLY, so an operator working continuously through a shift is never interrupted by a login.

## Primary ask — refresh-token flow (preferred)
1. Make `POST /v1/auth/exchange` ALSO return a `refresh_token`:
     { access_token, expires_in, refresh_token }
   - Opaque (not a JWT), server-side-backed, revocable, ROTATING preferred.
   - Its own longer lifetime: pick a value (or sliding window) that covers a full working shift, so an active operator never re-logs mid-work. Recommend a SLIDING session (each refresh extends it) OR an absolute TTL of ~8-12h. State what you choose.

2. Add `POST /v1/auth/refresh`:
     Request:  { refresh_token }
     200:      { access_token, expires_in, refresh_token? }   (refresh_token present iff rotating)
   - The new access_token carries the SAME claims as the original: sub, role, and all client-scope claims. Refresh must NOT broaden the visible-client set.
   - Auth: proof is the refresh_token ITSELF. Do NOT require the (expired) operator access token / bearer.
   - Errors:
       400  malformed body (missing refresh_token)
       401  refresh_token expired / revoked / unknown  -> CO falls back to full SSO login
       403  refresh_token valid but the user is no longer permitted
   - Rotation race: two concurrent refreshes with the same token -> EXACTLY ONE succeeds; the other gets 401 (CO serializes refreshes and retries the guarded call once).

## Alternative — silent authorize (if you prefer not to issue refresh tokens)
Support `GET /v1/auth/authorize?...&prompt=none`: when the DH SSO session (your own login cookie on the DH domain) is still alive, return a fresh ?code WITHOUT any user interaction; when it is not, return the usual interactive login (or an error CO can detect). CO then exchanges the code exactly as today.
Trade-off: silent-authorize renewal dies when the DH SSO cookie expires; a refresh_token is independent of it and more robust. Tell CO which you recommend.

## Security posture (keep)
- Access token stays SHORT-lived (~10 min) and JWT/JWKS-verified as today — do not lengthen it as the "fix".
- The refresh_token is the long-lived secret: bind it to user + SSO session, rotate on use, make it revocable, and store only a server-side reference.

## Open questions to answer back to CO
1. Does `/v1/auth/exchange` already return a `refresh_token` today? (CO reads none.)
2. Confirm the current access-token `expires_in` (is it ~600s?).
3. What lifetime does an SSO session (`/v1/auth/authorize`) currently honor?
4. Do you support (or can you add) `prompt=none` silent authorize?
5. Which do you recommend for CO — refresh-token or silent-authorize — and what concrete refresh-token TTL / sliding policy will you set?

## Acceptance
- `exchange` returns a usable `refresh_token`.
- `refresh` with a valid token -> a NEW, JWKS-verifiable access token whose claims (sub, role, client scope) match the original.
- Rotating: the old refresh_token is rejected after one successful refresh.
- Expired / revoked / unknown refresh_token -> 401. Malformed body -> 400. Access token supplied instead of refresh token -> rejected.
- Concurrent refresh with the same token -> exactly one succeeds.
- Refresh after the user's client ACL changed -> new access token reflects the change (never broadens it).

## Provider/integration tests (add)
- exchange returns refresh_token (happy path).
- refresh happy path: new access token verifies against JWKS; claims equal the original.
- rotation: reuse of a spent refresh_token -> 401.
- negatives: expired/revoked/unknown refresh_token -> 401; missing refresh_token -> 400; bearer-instead-of-refresh -> rejected.
- rotation race: two concurrent refreshes, exactly one 200.
- ACL change reflected in the refreshed token.

## CO side (for context — no DH action needed)
CO will: store the refresh_token httponly (separate from the access-token cookie); add a CO `/auth/refresh` route + a proactive keep-alive timer that refreshes before expiry; on catching `401 {code:"session_expired"}` it will try one refresh, and re-issue its session cookie via the refreshed access token. CO cannot mint or extend DH JWTs (they are DH-signed), which is why silent renewal must live in DH.

After building, report: refresh-token vs silent-authorize decision, the chosen refresh-token TTL / sliding policy, and the answers to the open questions above, so CO can wire the keep-alive timing and verify end-to-end.
```
