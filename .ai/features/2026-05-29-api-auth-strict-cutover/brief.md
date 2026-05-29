# Feature: Sister-app service-account JWT cutover + flip `api_auth_strict` (C.1 + C.2)

Discovery 2026-05-29. Consolidates BACKLOG C.1 (CO/BCQT adopt
service-account JWTs) and C.2 (promote `api_auth_strict=true`). C.1 is a
hard prerequisite for C.2 — they ship as a sequence, not together.

## Scope

**In:**
- Mint production service tokens for CO + BCQT (`scripts/mint_service_token.py`).
- Confirm both sister apps send a *valid Data Hub JWT* on every `/v1/hub/*`
  call (CO partially done; BCQT TBD — see Open Questions).
- Flip `api_auth_strict=true` on the prod instance once cutover verified.
- Remove the legacy permissive-bearer fallback in `app/routes/api.py:_require_token`
  (the `InvalidTokenError → return None` branch) *after* prod is stable on strict.
- Update `docs/API_CONTRACT.md` (drop dev-permissive section) +
  `docs/API_CHANGELOG.md`.

**Explicitly OUT:**
- No refresh-token flow (30d TTL + manual re-mint is the v1 contract; don't
  build an endpoint that doesn't exist).
- No change to cookie UI / `/api/v1/*` routes — strict only gates `/v1/hub/*`.
- No code-level default flip to `true` for fresh installs (see Risks #4).

## Dev impact (the headline question)

**Local Data Hub dev is unaffected.** `_strict_mode()` (`app/routes/api.py:51`)
only gates the `/v1/hub/*` Bearer API. Unaffected:
- Cookie UI + all page routes, `/api/v1/*` cookie routes.
- `scripts/smoke_real_uploads.py` + `scripts/screenshot.py` — both log in via
  cookie session (`/login`), never carry a `/v1/hub` Bearer.
- `pytest` — each auth test sets `api_auth_strict` explicitly (true/false) and
  resets it; baseline (1,260 passed) unchanged.

The flag lives in `hub.app_settings`, **per-instance**. Keep local + demo on
`false`, flip only prod. `DATA_HUB_API_AUTH_DISABLED=1` dev kill-switch still
works on non-strict instances (auto-suppressed when strict=true —
`app/main.py:89`).

**What does break under strict:** any `/v1/hub/*` caller sending a non-JWT
bearer — i.e. `Bearer dev` legacy strings + manual curl. That is exactly the
sister-app surface, which is why C.1 (cutover) gates C.2 (flip).

## Decisions

- **Sequence, not bundle:** C.1 cutover → soak on demo → C.2 flip. Demo box is
  the de-facto staging (no separate staging env exists).
- **Flip via setting, not migration:** `api_auth_strict` is an `app_settings`
  row. Promotion = `settings_store.set` on the target instance, not a schema
  migration. Code default stays `false`.
- **Service tokens are environment-bound by issuer** — see Risk #1. Mint prod
  tokens *on the prod instance* (or with `sso_issuer_url` already set to the
  prod URL), never copy a dev-minted token to prod.
- **Revoked service tokens never fall through to permissive** — already
  enforced (`ServiceTokenInvalid` → always 401, even in non-strict). No change
  needed; just noting the safety property holds.

## Risks

1. **Issuer pinning (localhost vs prod URL).** `verify_token` enforces
   `issuer=get_issuer_url()` exactly (`app/jwt_issuer.py:205`); default is
   `http://localhost:8754`, prod sets `sso_issuer_url=https://ttdatahub.tinsu.ai`
   (`docs/release-engineering.md:87`). A token minted before `sso_issuer_url`
   is set carries `iss=localhost:8754` and will **fail verification** once the
   setting flips. **Mitigation:** set `sso_issuer_url` on prod first, mint
   tokens after, verify with a real call before flipping strict. (Past incident
   on this exact mismatch — see CLAUDE.md "CO expected 127.0.0.1:8754".)

2. **30-day TTL = hard outage under strict.** No refresh flow. When a token
   expires, the sister app gets 401 until an admin re-mints + updates the env
   var. Under `strict=true` there's no permissive fallback to soften it.
   **Mitigation:** calendar reminder ~3 days before each token's `exp`;
   candidate for `/schedule`. Track `exp` per minted token.

3. **No staging.** C.2's original plan assumed a soak env. Reality: single VPS +
   demo box. Soak on demo (flip demo strict=true first, run CO consumer against
   it for ≥1 day) before touching prod. Keep the prod rollback trivial
   (`settings_store.set api_auth_strict=false`).

4. **Don't default fresh installs to `true` in code.** A fresh install with
   strict=true but no service tokens minted yet = sister apps locked out from
   first boot. Keep code default `false`; flip per-instance post-mint. (BACKLOG
   C.2 step 1 wording "default true in fresh installs" is the trap here.)

5. **Write endpoints are permissive in dev today.** `presets` POST/PATCH/tombstone
   and `parser-rules` POST/PATCH/DELETE use `_require_token` (permissive on
   non-JWT in non-strict), not `_require_jwt_claims` like bom/proposals does.
   Latent inconsistency — harmless once strict flips (both then require valid
   JWT), but worth a one-line note / optional tightening so dev instances don't
   accept anonymous writes. Not blocking.

6. **Removing the permissive branch is irreversible-ish.** Once
   `_require_token`'s `return None` fallback is deleted, every non-strict
   instance also rejects `Bearer dev`. Do this **last**, only after prod is
   stable on strict for a while — until then the flag alone is enough and keeps
   dev ergonomics.

## CO audit findings (2026-05-29 — both blocking questions resolved)

Audited `barry-CO-main/app/data_hub_client.py` + `co_auth.py` + `main.py`.

- **CO is uniform — single auth chokepoint.** Every `/v1/hub/*` call (`_get`,
  `_post`, `download_declarations_zip`) routes through `_auth_headers()`
  (`data_hub_client.py:448`). No per-path divergence. Whatever token that
  method resolves is sent on *all* paths.
- **Two token sources, both Data Hub-signed JWTs — neither is a legacy string:**
  1. `token_provider()` = ContextVar `current_data_hub_token`, set per HTTP
     request to `user.access_token` (`main.py:375`). `co_auth.py:40-73` proves
     `access_token` is a **Data Hub SSO-issued JWT** — CO verifies it against
     Data Hub's JWKS (EdDSA, kid, issuer). Takes precedence when present.
  2. `self.token` = `DATA_HUB_SERVICE_TOKEN` env (`data_hub_settings.py:73`).
     Fallback for paths with no user context (cron/background) +
     the settings health-check (`main.py:635`).
  - `_auth_headers`: `effective = token_provider() or self.token`. Interactive
    paths → user JWT; background paths → service token.
- **Conclusion: CO is already strict-compatible in prod**, conditional on:
  1. Users SSO through Data Hub (so `access_token` is DH-signed — confirmed by
     design), **and**
  2. `DATA_HUB_SERVICE_TOKEN` is set on prod CO to a real minted service token
     (covers background/cron paths + the health check).
  - In prod CO never sends `Bearer dev`. The only way strict breaks CO is a
    background path running with `DATA_HUB_SERVICE_TOKEN` unset → sends *no*
    Authorization header → 401. But that path already 401s today (no-bearer is
    rejected regardless of strict). So **strict changes nothing for CO** that
    isn't already broken. Risk #5 (write endpoints) likewise moot for CO.
- **BCQT is NOT a live consumer.** `grep "/v1/hub"` across `BCQT-System/app` +
  `scripts` = **0 hits**, no DataHubClient. So **C.2 only needs CO ready**;
  BCQT's `bcqt` service token can be minted lazily when its consumer-mode
  integration lands. Not a blocker.

## CO prod env check (2026-05-29 — done; found a blocker + a naming bug)

Inspected `co-app-1` container env + `~/co/.env` on the demo host
(`100.84.189.87`, CO prod = docker compose, `:8755`, talks to
`https://ttdatahub.tinsu.ai`).

- **No service token configured.** `DATA_HUB_SERVICE_TOKEN` is **absent** from
  the container env entirely. `api_token` resolves to `""` →
  `_auth_headers()` sends **no Authorization header** on any path that lacks a
  user context (health check at `main.py:635`, plus any cron/background path).
- **Env-key naming bug.** `~/co/.env` (and `.env.example:26` + `deploy/docker-deploy.md`)
  use `DATA_HUB_API_TOKEN`, but the code reads `DATA_HUB_SERVICE_TOKEN`
  (`data_hub_settings.py:73`). So even the empty `DATA_HUB_API_TOKEN=` present
  today is **silently ignored** — setting a token under that key would do
  nothing. Fix the key name in `.env.example`, the deploy doc, and the host
  `.env` when minting.
- **Issuer matches.** CO prod points `DATA_HUB_ISSUER_URL` + `DATA_HUB_API_BASE_URL`
  at `https://ttdatahub.tinsu.ai`, matching `sso_issuer_url=https://ttdatahub.tinsu.ai`
  (release-engineering.md). So user SSO JWTs verify cleanly — Risk #1 is not a
  problem for CO prod as configured.

**Net effect on the flip:** interactive CO paths (logged-in user → SSO JWT) are
safe under strict. The **service-token gap only bites no-user paths**, which
already 401 today (no-bearer is rejected regardless of strict). So strict does
not *newly* break CO — but to be correct + cover the health check + future cron,
mint a `bcqt`-style CO service token and set it under the right key **before**
flipping. This is the one concrete pre-flip action item.

## Open Questions
- **User-JWT TTL.** `user.access_token` is short-lived (login session). Under
  strict, an expired user JWT → 401 — but that already happens today (expired
  tokens always reject). Confirm CO's session refresh re-mints before expiry so
  interactive calls don't intermittently 401. Likely already handled by the SSO
  login flow; verify if 401s appear post-flip.
- **Prod client-id whitelist + `--created-by` for the service token.** Note
  example uses `growatt-vn,dke-vn,johnson-vn,do-thanh-vietnam-2614` — verify the
  live client-id set matches (e.g. `dke-vietnam-d0e3` vs `dke-vn`) when minting.

## Next step

`/discover` complete; CO audit done (both blocking questions resolved — CO is
uniform + already strict-compatible, BCQT not a live consumer). Recommended
path: (1) confirm `DATA_HUB_SERVICE_TOKEN` is set on prod CO + verify
`sso_issuer_url` on prod Data Hub, then mint the prod CO token (issuer set
first), (2) flip **demo** `api_auth_strict=true` and soak CO against it ≥1 day
(watch for interactive-path 401s = user-JWT TTL issue, and background-path 401s
= missing service token), (3) flip prod via `settings_store.set` with trivial
rollback, (4) mint BCQT token only when its consumer lands, (5) defer the
permissive-branch removal in `_require_token` to a later cleanup PR. The Data
Hub-side code work is near-zero — this is config + cross-repo sequencing.
