# Notes for CO + BCQT — service-account admin UI + 1-year default tokens

**Provider:** Data Hub · **Consumers:** CO, BCQT · **Date:** 2026-05-29

Amends `2026-05-02-service-account-jwts-available.md`. The token *contract*
(claim shape, scopes, `client_ids` whitelist, verification, revocation) is
unchanged — this note only adds a web UI for minting and changes the default
lifetime. **Nothing breaking for consumers.**

## What changed in Data Hub

1. **Admin web UI for service accounts** — `/admin/service-accounts` (dev-only).
   List / create (with one-time token reveal) / delete / revoke-jti. Wraps the
   same registry + issuer the CLI uses. Minting via the prod web UI binds the
   token to the prod issuer + signing key automatically (no more "minted on
   localhost → wrong `iss`" footgun). The CLI (`scripts/mint_service_token.py`)
   still works for headless/scripted use.

2. **Default token TTL: 30d → 1 year** (mig 074). Service accounts are
   long-lived static keys, rotated yearly by **re-mint** (delete + create, or
   create a fresh name), not auto-renewed. Custom expiry selectable per mint.

3. **No auto-renew / refresh flow.** A sliding-expiry mechanism was prototyped
   then dropped — the 2026-05-02 stance ("no refresh flow; admin re-mints before
   expiry") **still holds**, just with a 1-year instead of 30-day cadence.

Migrations: **073** (`service_accounts.token_expires_at`, operational metadata),
**074** (default TTL → 1y; drops the abandoned `auto_renew` column).

## Action required — CO (operational, found during 2026-05-29 audit)

CO's `data_hub_client` reads the env var **`DATA_HUB_SERVICE_TOKEN`**
(`app/data_hub_settings.py`). But `~/co/.env`, `.env.example`, and
`deploy/docker-deploy.md` use **`DATA_HUB_API_TOKEN`** — a name the code
**silently ignores**. CO prod (`co-app-1` on the demo box) currently has **no
service token in effect**:

- Interactive paths are fine — they carry the logged-in user's Data Hub SSO JWT.
- No-user paths (cron/background, the settings health-check) send no bearer →
  already 401 today, and will stay 401 under `api_auth_strict=true`.

To fix before the C.2 strict cutover:
1. Mint a CO token (1y, `hub:read,bom:propose`, client whitelist for CO's
   agencies) via `/admin/service-accounts` on prod or the CLI.
2. Set it under the **correct** key `DATA_HUB_SERVICE_TOKEN` in `~/co/.env`;
   fix `.env.example` + `deploy/docker-deploy.md` to match.
3. `docker compose up -d` to reload.

## Action required — BCQT

None yet — BCQT is not a live `/v1/hub/*` consumer (0 call sites as of
2026-05-29). Mint a `bcqt` token (`hub:read`) when consumer-mode integration
lands.

## Reference

- Feature brief: `.ai/features/2026-05-29-service-account-admin-ui/brief.md`
- Cutover discovery: `.ai/features/2026-05-29-api-auth-strict-cutover/brief.md`
- Token contract (unchanged): `2026-05-02-service-account-jwts-available.md`
