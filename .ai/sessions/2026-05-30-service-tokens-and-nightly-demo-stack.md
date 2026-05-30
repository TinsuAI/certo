# Session 2026-05-29/30 — Service-account UI + nightly/demo stack

Long session spanning two pieces of work: (1) the service-account token admin UI
+ C.1/C.2 discovery, and (2) a brand-new nightly/demo stack for Data Hub + CO on
the demo box, behind public HTTPS domains.

## What Was Done

### Part 1 — Service tokens (Data Hub repo)
- **C.1/C.2 discovery** (`.ai/features/2026-05-29-api-auth-strict-cutover/brief.md`):
  audited the api-auth-strict cutover. Found `_strict_mode()` only gates
  `/v1/hub/*`; cookie UI + scripts unaffected. Audited CO `data_hub_client.py`:
  single auth chokepoint, sends either the user SSO JWT or `DATA_HUB_SERVICE_TOKEN`
  (both Data Hub-signed). BCQT not a live consumer (0 call sites). **Found a bug:**
  CO's `.env`/`.env.example`/deploy-doc use `DATA_HUB_API_TOKEN`, but the code
  reads `DATA_HUB_SERVICE_TOKEN` → CO prod has no service token in effect.
- **Service-account admin UI** (`/admin/service-accounts`, dev-only) —
  list/create(one-time reveal)/delete/revoke-jti. Wraps `sa_store` +
  `jwt_issuer.make_service_token`. Commits `a7d3422` → `7d576ed`.
- **Expiry pick/display** (mig 073 `token_expires_at`) + **default TTL 30d→1y**
  (mig 074). Rotation by re-mint.
- **Sliding auto-renew was prototyped then reverted** — see Decisions.
- Sister-app note `2026-05-29-service-account-admin-ui-and-1y-tokens.md` +
  DECISIONS entry. Merged to main, deployed to demo (CI green, mig 074 applied,
  route 401-gated = live).

### Part 2 — Nightly/demo stack (NEW repo `TinsuAI/tinsu-deploy`)
- Dedicated deploy repo: one `docker-compose.nightly.yml` (4 services, project
  `nightly`, ports 8764/8765, isolated volumes/db), `.env.nightly.template`,
  and scripts: `snapshot-prod-to-nightly.sh`, `mint-nightly-token.sh`,
  `ensure-demo-user.sh`, `nightly-build.sh`, `rebuild-app.sh`, `refresh-now.sh`.
  Full guide in `tinsu-deploy/docs/RUNBOOK.md`.
- **Live + verified end-to-end:** https://demo-datahub.tinsu.ai +
  https://demo-co.tinsu.ai (public, via the existing Cloudflare tunnel). SSO
  cross-domain login works; CO pulls real prod data from DH.
- **On-merge trigger:** Data Hub `ci-cd.yml` (`a2db96f`,`b3f8104`) + CO `ci.yml`
  both end with a `continue-on-error` step that rebuilds the matching nightly
  service after a prod deploy. Verified live on both.
- **Stable demo login:** `demo@tinsu.ai` / role admin (password in box
  `.env.nightly` `DEMO_USER_PASSWORD`), re-created after every snapshot.
- Data = full prod snapshot, **unmasked** (accepted risk). Nightly cron 02:30
  refreshes; `refresh-now.sh` for pre-demo.

## Decisions Made
- **Service tokens = static 1-year keys, not auto-renew.** Sliding/registry-
  enforced expiry was built (`f16a29e`) then dropped (`47e51ab`): non-standard
  for M2M, changed the hot verify path. Conventional pattern (long-lived bearer
  + revocation list) fits the scale. OAuth2 client-credentials noted as the
  "proper" future direction. (DECISIONS 2026-05-29.)
- **Nightly stack: dedicated deploy repo**, same VPS (isolated), full prod data
  no-masking, both triggers (on-merge + nightly cron). User explicitly accepted
  the client-data-exposure risk (twice).
- **Demo user is admin** (cross-client visibility), re-created post-snapshot.

## What Didn't Work
- `pg_dump --clean` into existing DB → can't drop `hub` schema (pg_trgm/vector
  dep). Fix: drop+recreate DB + plain restore.
- `DROP DATABASE` via one `psql -c` with two statements → "cannot run inside a
  transaction block". Fix: separate `-c` flags.
- Cron logging to `/var/log` → tinsu can't write. Fix: `~/nightly-build.log`.
- **sudo-rs 0.2.8 does NOT honor a scoped NOPASSWD drop-in** (blanket
  `(ALL:ALL) ALL` wins). Installed `/etc/sudoers.d/tinsu-cloudflared` but it has
  no effect — root tunnel ops still need an interactive password.
- **Editing `/etc/cloudflared/config.yml` did nothing** — the tunnel
  `tinsu-online-server` is **dashboard-managed** (remote config). Public
  hostnames must be added in the Cloudflare Zero Trust dashboard (done) or via
  API. `cloudflared tunnel route dns` still works for DNS.

## Open Items
- **SSO browser login** verified for the nightly stack; the prod-side C.2 strict
  cutover is still NOT done — see `.ai/features/2026-05-29-api-auth-strict-cutover/brief.md`.
  Before flipping `api_auth_strict=true` on prod: mint a CO prod service token,
  set it under the correct key `DATA_HUB_SERVICE_TOKEN` (fix the
  `DATA_HUB_API_TOKEN` bug in CO's `.env`/example/deploy-doc).
- **CO `app/main.py`** shows as modified in the local checkout — pre-existing,
  NOT from this session; left untouched.
- Nightly stack follow-up: watch box RAM; on-merge rebuilds only code (data on
  cron). Future tunnel domains → CF dashboard, not config.yml.
