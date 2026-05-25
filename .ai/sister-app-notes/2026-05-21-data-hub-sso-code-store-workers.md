# Data Hub SSO Code Store Breaks With Multi-Worker Uvicorn

Date: 2026-05-21
Consumer: CO (`barry-CO-main`)
Provider: Data Hub

## Problem
CO browser login can fail with:

`Data Hub login failed. Check Technical Settings for issuer/JWKS and Data Hub SSO config.`

The local Data Hub instance was running:

`uv run uvicorn app.main:app --host 127.0.0.1 --port 8754 --workers 4`

Data Hub's SSO implementation stores one-time browser SSO codes in a module-level in-memory dict:

`app/routes/auth_api.py::_SSO_CODES`

With multiple uvicorn workers, `/v1/auth/authorize` may create the code in worker A, while CO's `/auth/callback` exchanges the code through `/v1/auth/exchange` on worker B. Worker B cannot see worker A's in-memory code and returns `401 invalid or expired code`. CO then surfaces the generic login failure.

## Evidence
- Data Hub `/healthz` returned `200`.
- Data Hub `/v1/auth/jwks` returned `200`.
- CO Technical Settings pointed to local Data Hub:
  - `DATA_HUB_BASE_URL=http://127.0.0.1:8754`
  - `DATA_HUB_API_BASE_URL=http://127.0.0.1:8754`
  - `DATA_HUB_ISSUER_URL=http://127.0.0.1:8754`
  - `DATA_HUB_JWKS_URL=http://127.0.0.1:8754/v1/auth/jwks`
- CO log showed repeated `/auth/callback?...` responses with `401 Unauthorized`.
- Restarting Data Hub as a single-worker uvicorn process made SSO stable.

## Local Workaround
Run Data Hub local dev with one worker:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8754
```

Avoid `--workers 4` until the SSO code store is shared across workers.

## Recommended Data Hub Fix
Move one-time SSO authorization codes out of process memory into a shared store.

Recommended implementation:
- Add a Postgres-backed `hub.sso_authorization_codes` table.
- Store `code_hash`, `user_id`, `email`, `role`, `display_name`, `redirect_uri`, `expires_at`, `consumed_at`, `created_at`.
- Store only a hash of the code, not the raw code.
- On `/v1/auth/authorize`, insert the code row with a short TTL.
- On `/v1/auth/exchange`, atomically consume the row with `consumed_at is null and expires_at > now()`.
- Delete or periodically purge expired rows.
- Add provider tests proving exchange works across independent app instances/processes.

Alternative acceptable fix:
- Use Redis or another shared cache with atomic get-and-delete semantics.

## Acceptance Criteria
- Data Hub can run with `--workers 4` and CO SSO login succeeds repeatedly.
- Reusing the same SSO code still fails.
- Expired SSO codes fail.
- Redirect URI binding remains enforced.
- JWKS/issuer validation remains unchanged.
