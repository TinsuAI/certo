# Project Status

**Date:** 2026-06-01 — Shipped the CO-requested **BOM artifacts batch endpoint**
(`POST /v1/hub/products/bom/artifacts:batch`) plus an ARTIFACT FIELD PARITY fix and a
new single-artifact route; pushed + auto-deployed to the nightly stack. Then scoped
the CO↔DH internal-network question (mostly answered from local recon). See
`.ai/sessions/2026-06-01-bom-artifacts-batch-endpoint.md`.

## Current State

**Branch:** `main` at `9408c8f`, pushed. **Tests:** 1296 passed, 15 skipped
(`uv run pytest -q`). **Migrations:** 074 (no new migration — additive query/route only).

**This session's commits:**
- `9408c8f` — fix(api): batch items carry full single-artifact shape (ARTIFACT FIELD PARITY)
- `64d2761` — feat(api): POST /v1/hub/products/bom/artifacts:batch

**New endpoints (CI-deployed; verified live on nightly `:8764`):**
- `POST /v1/hub/products/bom/artifacts:batch` — multi-product fan-in of the picker.
- `GET /v1/hub/products/{pc}/bom/artifacts/{artifact_id}` — single artifact, full shape.

**Uncommitted:** `AGENTS.md` (worker-note rewrite; `CLAUDE.md` symlinks to it).

**Box (`100.84.189.87` = `tinsu-online-server`):** prod DH `:8754` and CO `:8755` run as
**Docker** (`data-hub-app-1` / `co-app-1`, DBs `data-hub-db-1` / `co-db-1`), NOT systemd
(repo's `deploy/systemd/*.service` is stale — verified live 2026-06-01). They are on
**separate docker networks** (`data-hub_default` vs `co_default`). Nightly/demo stack is a
separate compose project (`nightly-*`, `:8764`/`:8765`, `tinsu-deploy`); CI auto-refreshes
it on merge to main — confirmed green this session. Prod CO→DH calls currently use the
**public domain** `https://ttdatahub.tinsu.ai` (round-trips out to Cloudflare and back).

## Recent Changes (this session)
- **BOM artifacts batch endpoint** + **ARTIFACT FIELD PARITY** fix. CO e2e found batch
  items came from the LIST summary (7 diagnostic fields NULL vs the single-artifact path);
  fixed by fanning in the full single-artifact shape via `list_artifact_meta_for_products`,
  which shares `_ARTIFACT_META_COLS` with `get_artifact_with_rows` so the two can't drift.
  20 batch provider tests. **CO to run final e2e, then switch on the batch path.**
- Rewrote the `--workers` note in `AGENTS.md`: real reason for >1 worker is `async def`
  routes doing blocking sync DB I/O (event loop blocks → workers, not async, are the
  concurrency mechanism); the old "sister-app fan-out" rationale is moot post-batch-endpoint.
  (Committed `e467a66`, not yet pushed.)

## Next Steps
1. **CO↔DH over Docker internal network — DONE 2026-06-01.** Both `app` containers join
   external net `tinsu-shared` (DH alias `data-hub-app`). Prod CO `.env` now:
   `DATA_HUB_API_BASE_URL=http://data-hub-app:8754` (data calls) AND
   `DATA_HUB_JWKS_URL=http://data-hub-app:8754/v1/auth/jwks` (key fetch) — **both internal**,
   so the entire CO→DH path (data + auth) no longer touches the internet. `DATA_HUB_BASE_URL`
   (browser SSO redirect) and `DATA_HUB_ISSUER_URL` (iss identifier, string-match only — not a
   fetch) stay public `https://ttdatahub.tinsu.ai` by design. `networks:` blocks committed in
   both repo composes (DH `48d874b` → origin, CO `5ce27f3` → `tinsu` remote = TinsuAI/co;
   origin `sgnjfk/*` is a FORK, do not push prod there). Both CI deploys green. Verified:
   co-app→data-hub-app:8754/v1/hub/dncxs=200, batch=400(missing_client_id); pre-flip JWKS
   internal==public (keys=1, kid=k1, same key); post-JWKS-flip CO healthy, jwks=200 from
   container, no error/jwks/issuer logs, public CO+DH=200. `.env` backups on box:
   `/home/tinsu/co/.env.bak-20260601-004118` (pre-API-flip) and `.env.bak-jwks-*` (pre-JWKS-flip)
   — rollback is one sed line each + `docker compose up -d app`. NOTE: these are box-side
   gitignored `.env` edits; CI resets code only, never `.env`.
   **Final acceptance still TODO (needs a human/browser):** log into CO and load a
   BOM workspace to confirm the authenticated SSO round-trip + DH-backed data fetch
   (now verifies the token signature via the *internal* JWKS). Prompt for the CO-side AI to
   run this was handed to the user.
2. Decide whether to commit the `AGENTS.md` worker-note change.
3. **C.2 strict cutover (prod)** — still open from 2026-05-30: mint CO prod service token,
   fix CO `DATA_HUB_API_TOKEN`→`DATA_HUB_SERVICE_TOKEN` env-key bug, flip `api_auth_strict=true`.
   Brief: `.ai/features/2026-05-29-api-auth-strict-cutover/brief.md`.
4. Backlog (C.1 sister-app cutover, D.1 aggregate-data history, A.3/A.4.2, B.1, B.5) — `.ai/BACKLOG.md`.

## Notes for Next AI Session
- **CO↔DH wiring map** (this session's recon): CO `app/data_hub_settings.py` = the 4 URLs;
  `app/co_auth.py` = JWT verify (multi-issuer tuple + JWKS fetch/cache);
  `app/data_hub_client.py` uses `data_hub_api_base_url`. DH issues `iss` from
  `settings_store.get("sso_issuer_url")` (DB setting, default `http://localhost:8754`),
  independent of its listen URL.
- **Tooling quirk this session:** agent Bash/Read output buffered heavily and flushed in
  late bursts; background-to-file + completion notifications were the reliable pattern.
- **Use Windows `ssh.exe`** (`/mnt/c/Windows/System32/OpenSSH/ssh.exe`); `ssh tinsu@100.84.189.87`.
  Nightly docs: `~/workspace/client/tinsu-deploy/docs/RUNBOOK.md`.
- **Demo creds:** `demo@tinsu.ai`, password in `~/tinsu-deploy/.env.nightly` on the box.
- Untracked pre-existing files (not this session): `.ai/sessions/2026-05-15*`, `-25*`, `-28*`,
  `-29*`, `scripts/generate_training_input_scenarios.py`, `scripts/uom_drift_report.py`,
  `docs/training/`. Repo-hygiene triage later.
