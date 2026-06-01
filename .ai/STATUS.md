# Project Status

## Current State
- Branch `main` at `0ebba12` — pushed to `tinsu/main` + deployed (CI/CD green).
  Working tree clean. Local suite **403 passed + 8 skipped** (file-store/CI mode).
- **DH↔CO internal-network + JWKS cutover — DONE, prod-verified (2026-06-01).**
  CO→Data Hub server-to-server now rides the internal docker bridge `tinsu-shared`
  (DH alias `data-hub-app`): prod `.env` `DATA_HUB_API_BASE_URL` **and**
  `DATA_HUB_JWKS_URL` = `http://data-hub-app:8754...`. `DATA_HUB_ISSUER_URL` +
  `DATA_HUB_BASE_URL` stay public (`https://ttdatahub.tinsu.ai`).
  - **Safe because `iss` validation is independent of call/JWKS-fetch URLs**
    (`data_hub_settings.py`: issuer←ISSUER_URL/BASE_URL, jwks←issuer, neither from
    API_BASE_URL; `DataHubTokenVerifier` checks `iss` vs public issuer). Tokens
    still carry `iss=https://ttdatahub.tinsu.ai` (password-grant + SSO cookie).
  - Verified: internal reachability 200; latency ~22ms vs ~174ms public (~8x);
    50-product johnson BOM workspace **64ms via batch over internal** vs ~10.4s
    public-sequential baseline; **browser SSO e2e** (Playwright) login → exchange →
    BOM renders, 0 auth/console errors, co-app-1 logs clean. Screenshots:
    `.ai/screenshots/dh-internal-network-verify/`.
- **BOM workspace perf — DONE, deployed.** (a) Parallel per-product fetch capped at
  `BOM_FETCH_MAX_WORKERS=4` (8 regressed against single-worker DH); (b) **batch
  endpoint consumer** `POST /v1/hub/products/bom/artifacts:batch` via
  `list_bom_artifacts_batch` + `_build_workspace` batch-first with per-product
  fallback (404-memoized). Batch is **live on prod DH** → prod CO uses it (one
  round-trip). Functionally equivalent to per-product (13 differing artifact fields
  are all unused in CO; counts/rows/`origin_build_signature` identical). Tests:
  `tests/test_bom_workspace_parallel.py`, `tests/test_bom_workspace_batch.py`.
- **Earlier-shipped, still current:**
  - Origin tab full-BCCT pull eliminated (snapshot + narrow invoice_matches); cold
    `/origin` ~1.47s prod (`b3d6083`).
  - Case-detail (shipment) load fix via `skip_heavy_context` (~21s → ~1.5–3.6s,
    `d28e237`).
  - No-silent-local-fallback: DH off→503, unreachable→503/502; opt-in local via
    `CO_ALLOW_LOCAL_SOURCE=1`. `tests/test_source_backend_guard.py`.
  - Claim-ID stability keyed on `material_code` (`24d4731`).

## Recent Changes (2026-05-31 → 06-01 session)

Full detail: `.ai/sessions/2026-06-01-bom-batch-and-dh-internal-network.md`.

| Commit | Topic |
|---|---|
| `0ebba12` | docs: DH JWKS flipped internal, CO re-verified (SSO + BOM) |
| `3a7745a` | docs: DH↔CO internal-network cutover verified |
| `5ce27f3` | deploy: attach app to external `tinsu-shared` network |
| `ea17e59` | docs: batch consumer verified functionally equivalent |
| `a91e97a` | feat(bom): consume DH batch BOM artifacts endpoint + fallback |
| `5e36b96` / `3ddb659` | docs: DH batch API request + DH implementation prompt |
| `6eddef9` | perf(bom): cap BOM fetch concurrency 8 → 4 |
| `2c0ff21` | perf(bom): parallelize per-product DH fetch |

## Next Steps (deferred — no code yet unless noted)

1. **Origin lock TTL cleanup** (60-min stale lock).
2. **Customs FX historical backfill.**
3. **Seed missing CO forms** — D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ.
4. **HS↔form coherence + criteria token validation** (MED).
5. **Claim-identity DB unique constraint** `(client_id, case_id, sheet_product_code,
   source_row, material_code)` — app-only today. See
   `.ai/features/2026-05-29-claim-id-stability.md`.
6. **CO-stock scheduled freshness refresh** — refresh-on-access already exists.
7. **Recommend to DH owner:** prod DH still runs `--workers 1` on a 24-core box —
   internal networking removed proxy/TLS overhead but DH is still single-process.
8. **Prod CO↔DH backend auth cutover** — deferred by user (low risk, one company).
9. **`can_view_client` short→long fallback** — confirmed NOT a real prod bug; do not
   add fuzzy-match fallback.

## Notes for Next AI Session
- **Memory** at `/home/vp/.claude/projects/-home-vp-workspace-client-barry-CO/memory/`
  — read `MEMORY.md` first. Key: `demo-server-ssh` (SSH, containers, internal net +
  JWKS-internal), `bom-batch-endpoint-and-parity`, `dh-bcct-declaration-filter-singular`,
  `no-silent-local-fallback`, `test-local-by-default`.
- **Test on local by default.** Only touch prod when explicitly told.
- **Prod box:** SSH `tinsu` (Tailscale `100.84.189.87`). Containers `co-app-1`,
  `co-db-1`, `data-hub-app-1`, `data-hub-db-1`. Prod CO `:8755`, DH `:8754`. `.env`
  backup `/home/tinsu/co/.env.bak-20260601-004118`. Deploy = push `tinsu/main` →
  CI/CD (tests+docker+deploy+nightly refresh).
- **Prod test account:** `claude-check@local` / `claude-temp-2026` (manager,
  growatt-vn + johnson-vn). Use long client IDs (`johnson-vn`); short forms 403.
  Product-heavy prod case: `co-case-0605189d5eea`.
- **DH is a separate repo** (`~/workspace/client/data-hub`, `TinsuAI/data-hub`) —
  sibling checkout; its AGENTS.md treats CO repo as a sister repo. CO never edits DH
  endpoints from this repo (guardrail `tests/test_data_hub_policy.py`); new endpoints
  go through `.ai/api-requests/` + DH approval.
- **Playwright available** in `.venv` (chromium installed) — used for browser SSO e2e.
  Save screenshots under `.ai/screenshots/<feature-slug>/`.
- **BOM workspace cache** (`bom_service.py`): in-process per worker, TTL 60s. Prod
  runs multiple workers → cold-worker re-pay until warmed (not a bug). Batch support
  memoized in `_DATA_HUB_BOM_BATCH_SUPPORTED` (cleared with the workspace cache).
- **Run suite WITHOUT sourcing `.env`** (`env -u BARRY_DATABASE_URL -u
  DATA_HUB_ENABLED -u DATA_HUB_SERVICE_TOKEN`) to mirror CI/file-store mode; sourcing
  `.env` drives the real local DB/DH and can cause spurious failures.
