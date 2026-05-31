# Session: BOM artifacts batch endpoint + CO↔DH networking question (2026-06-01)

## Goal
Build the CO-requested batch read endpoint for BOM artifacts (fan-in of the
per-product picker), then fix a parity gap CO found in e2e testing. Tail end:
started scoping whether CO↔DH should talk over Docker's internal network.

## Done
- **`POST /v1/hub/products/bom/artifacts:batch`** (commit `64d2761`). Multi-product
  fan-in of `GET /products/{pc}/bom/artifacts`. Reuses `_apply_bom_artifact_filters`
  + batched row fetchers. Opaque cursor pagination, never splits a product across
  pages. `missing[]` for zero-artifact codes. scope `hub:read` + client scoping.
  19 provider tests.
- **ARTIFACT FIELD PARITY fix** (commit `9408c8f`). CO e2e found batch items came
  from the LIST summary → 7 fields NULL vs the single-artifact path
  (`client_id, flatten_method[_version], lineage, stale_first_at, stale_resolved_at,
  uom_drift_resolved_at`). Fix: new `list_artifact_meta_for_products` fans in the
  FULL single-artifact column set, sharing `_ARTIFACT_META_COLS` with
  `get_artifact_with_rows` so the two shapes can't drift. Batch items now built from
  it. +ARTIFACT FIELD PARITY test (20 batch tests total). Full suite **1296 passed**.
- **New route** `GET /v1/hub/products/{pc}/bom/artifacts/{artifact_id}` — the single
  -artifact endpoint CO's contract assumed but DH never had (DH only exposed the rich
  object via `/bom?artifact_id=`). Returns canonical rich artifact, client/product
  -scoped, 404 on mismatch.
- Pushed `main` (`f23b091..9408c8f`) → CI/CD `26716832669` green incl. "Refresh
  nightly stack". Verified live on `:8764`: new routes 401 (deployed), bogus 404.
  **CO can run final e2e + switch on the batch path.**
- Updated worker note in `AGENTS.md` (CLAUDE.md → symlink). **UNCOMMITTED.**

## Decisions
- Parity target = the single-artifact `artifact` shape, NOT the lighter `/bom/artifacts`
  LIST summary. Single-sourced the column list to prevent future drift.
- Added the `/bom/artifacts/{id}` REST route rather than only testing against
  `?artifact_id=` — CO's contract treats it as existing; low-risk + additive.
- Batch defaults = picker contract (active/flat/latest), not the per-product
  back-compat defaults (all/any/false). Parity holds on same explicit filters.

## Didn't work / dead ends
- Tooling in this session intermittently buffered/dropped tool output (foreground
  results flushed in late bursts). Worked around via background-to-file + notifications.
  Initial reads were briefly corrupted (showed `...` stubs / a non-existent
  `app/routers/hub_products.py`) — real router is `app/routes/api.py`.

## Open / next steps
- **CO↔DH internal Docker networking** (user question — largely ANSWERED by local
  recon; only live-prod confirmation left):
  - GATING QUESTION ("does CO decouple call-URL from trusted-issuer?") = **YES.**
    `barry-CO-main/app/data_hub_settings.py` holds four independent vars:
    `DATA_HUB_BASE_URL` (browser SSO redirects), `DATA_HUB_API_BASE_URL` (server→server
    calls), `DATA_HUB_ISSUER_URL` (iss validation), `DATA_HUB_JWKS_URL`. `co_auth.py`
    verifies JWT against a **tuple of issuers** (`data_hub_issuer_urls()`, loops, accepts
    any) with JWKS fetch+cache. So changing the API call URL does NOT touch `iss`.
  - **Nightly stack already does this:** `tinsu-deploy/docs/RUNBOOK.md:91` — "CO→DH
    server-to-server uses the internal name `http://dh-app:8754`". So for docker, it's
    already implemented; nothing to do there.
  - **CORRECTION (verified live 2026-06-01):** PROD IS DOCKER, not systemd. systemd
    `data-hub`/`co` are inactive; the repo's `deploy/systemd/data-hub.service` is stale.
    Prod = `data-hub-app-1` (`:8754`, net `data-hub_default`) + `co-app-1` (`:8755`, net
    `co_default`) — **two separate compose projects / networks**. So they can't reach each
    other by container name today.
  - **Prod CO→DH today = the PUBLIC domain.** `docker exec co-app-1 printenv`:
    `DATA_HUB_API_BASE_URL=DATA_HUB_BASE_URL=DATA_HUB_ISSUER_URL=https://ttdatahub.tinsu.ai`,
    `DATA_HUB_JWKS_URL=https://ttdatahub.tinsu.ai/v1/auth/jwks`. So server-to-server calls
    round-trip out to Cloudflare and back — exactly what the user wants to eliminate.
    Compose dirs: `/home/tinsu/data-hub`, `/home/tinsu/co`, `/home/tinsu/data-hub-stage`
    (staging), `/home/tinsu/actions-runner-data-hub`.
  - **PROPOSED FIX (pending user approval — prod change, do in daylight):** create/attach a
    shared external docker network to both `data-hub` and `co` compose projects; give DH a
    network alias (e.g. `data-hub-app` — both projects have a service literally named `app`,
    so a distinct alias is required); set prod CO `DATA_HUB_API_BASE_URL=http://data-hub-app:8754`.
    KEEP `DATA_HUB_ISSUER_URL`/`DATA_HUB_JWKS_URL`=`https://ttdatahub.tinsu.ai` (canonical
    `iss`; CO decouples + multi-issuer) and `DATA_HUB_BASE_URL` public (browser). Optionally
    also internalize JWKS. Verify with `docker exec co-app-1 curl -fsS http://data-hub-app:8754/v1/hub/dncxs`
    + a real SSO/login round-trip before declaring done.
- Decide whether to commit the `AGENTS.md` worker-note change (uncommitted).

## Key context
- `iss` pinning: DH must keep issuing the canonical issuer string for browser SSO;
  changing CO's *call URL* must not change the *issuer it trusts*. This is the whole
  risk of the docker-network change.
- Prod = systemd units on `100.84.189.87` (`:8754`); nightly/demo = docker compose
  (`tinsu-deploy`, `:8764/:8765`). User explicitly wants the PROD config inspected.
- SSH: use Windows `/mnt/c/Windows/System32/OpenSSH/ssh.exe` (WSL ssh broken);
  server `100.84.189.87`, clone `/home/tinsu/data-hub`.
