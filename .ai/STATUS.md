# Project Status

## Current State
- Branch `main`: 4 commits on base `83efe8d` — `d28e237` (perf skip_heavy_context
  + no-silent-local-fallback guard), `e76a526` (STATUS), `dbb9315` (map DH
  outages to 503/502 + 3 regression tests), then this STATUS commit. Committed
  locally, **not pushed**.
- Local suite **389 passed + 7 skipped**.
- **Case detail load fix DONE and E2E-verified** against the local Data Hub
  (johnson-vn, 12.5k materials / 66k BCCT): origin/old path 39.7s → shipment
  light path 0.03s, 82 → 2-3 round trips, invoice_matches parity preserved.
- **No-silent-local-fallback DONE (both branches).** CO never serves local
  backup data when Data Hub is the source of truth:
  - `DATA_HUB_ENABLED` off + `CO_ALLOW_LOCAL_SOURCE` unset → 503
    (`SourceBackendUnavailable`) at the single chokepoint
    `app/portfolio.py:get_portfolio_service()`.
  - `DATA_HUB_ENABLED` on but API unreachable → 503 (`httpx.TransportError`
    handler); DH returns an unhandled error status → 502
    (`httpx.HTTPStatusError` handler). Both fire only for unhandled exceptions,
    so routes that intentionally catch DH 404s (fallbacks) are unaffected.
  - Tests/dev opt into local via `CO_ALLOW_LOCAL_SOURCE=1` (conftest autouse).
    Regression tests: `tests/test_source_backend_guard.py` (6 tests).
- Local dev `.env` now points CO at the local Data Hub on :8754
  (`DATA_HUB_ENABLED=1`, `DATA_HUB_SERVICE_TOKEN=co-service`, auth off).

## Recent Changes (2026-05-30 session)

| Commit | Topic |
|---|---|
| `d28e237` | perf: `skip_heavy_context` — non-origin case steps skip materials+BCCT pagination (39.7s→0.03s on Johnson); + no-silent-local-fallback guard (DH off→503) |
| `dbb9315` | map DH outages to 503 (TransportError) / 502 (HTTPStatusError) instead of generic 500; 3 regression tests |
| `ad17bb3` | perf: preload in background thread (necessary but insufficient — superseded by `d28e237`) |

## Recent Changes (2026-05-29/30 session)

| Commit | Topic |
|---|---|
| `2b9c535` | Guard `data_hub_target_url` against empty deep-link — only emit when a real DH page exists; 4 templates wrap the "Mở DH" button in `{% if data_hub_target_url %}` |
| `24d4731` | **Claim ID stability** — `claim_id_for` keyed on `material_code` (not BOM position); `_build_claim_rows` sums qty on collision (fixes latent under-claim). 6 DB-free unit tests + 3 Postgres-gated e2e tests pass. Brief: `.ai/features/2026-05-29-claim-id-stability.md` |
| `cdbeef2` | STATUS update |
| `5d34ed8` | CI: nightly CO stack refresh after prod deploy (on-merge trigger) — user committed separately |
| `ea25b36` | CI: self-pull tinsu-deploy before nightly refresh — user committed separately |

## Next Steps

1. **Case detail load (shipment tab) ~21s — DONE, deployed, prod-verified.**
   `skip_heavy_context` on `co_case_source_context` (commit `d28e237`, deployed
   via CI run `aab0957`). Prod benchmark (`johnson-vn / co-case-0605189d5eea`,
   Bearer JWT for `claude-check@local`): shipment tab **~1.5–3.6s** vs ~21s
   baseline (~7–10x). invoice_matches parity preserved (local E2E: 39.7s→0.03s).

2. **Origin tab is now the dominant bottleneck (NEW, HIGH).** Same prod case,
   `/origin` measured **34.5s, 140s, and one 503 timeout at ~41s**. The origin
   step still does the full `list_materials` + `list_bcct` pagination (by
   design — it needs material/stock rows), so it didn't benefit from
   `skip_heavy_context` and is heavier than the old 21s baseline.

   **Profiled (2026-05-31, johnson-vn on local DH), origin path = 64.85s:**
   - `list_bcct` full 66k rows = **36.15s** ← main culprit (paginated, ~66 RTs)
   - `list_materials` 13k rows = 3.67s
   - `co_stock_rows_from_bcct` (local CPU) = 2.39s
   - remainder (~22s) = `bom_service.workspace` (BOM artifacts fetch)

   **Recommended fix — narrow BCCT fetch (no new DH endpoint needed):**
   Origin only consumes `stock_rows`/`material_rows` via `case_allocation_pool`
   (pools stock by material_code) and `material_catalog_index` (BOM-material
   lookup) — i.e. it only needs stock for materials in THIS case's BOM (tens of
   rows), not all 66k. The substitute modal already does this:
   `main.py:~2510` uses `list_bcct_by_codes(material_codes)` (narrow endpoint,
   already approved + in adapter). Plan: in `co_case_light_context` for the
   origin step, reorder to fetch invoice_matches → bom_workspace → derive the
   case's material codes → `list_bcct_by_codes` instead of full `list_bcct`.
   Expected: origin ~65s → ~24s (BOM workspace then becomes next bottleneck).

   **Two risk points — do `/discover` then `/tdd`, NOT a quick fix:**
   (1) origin RVC/LVC parity is a high-risk area (CLAUDE.md); reordering the
   central `co_case_light_context` must not change calc results.
   (2) `origin_build_signature` (origin-snapshot cache key, `main.py:3169`)
   hashes `stock_rows` — narrowing stock changes the signature; verify it
   doesn't break snapshot reuse / force needless recompute.
   Benchmark harness: Bearer JWT via DH `/v1/auth/token` for `claude-check@local`,
   then `curl -w %{time_total}` the `/origin` route (case
   `johnson-vn / co-case-0605189d5eea`). Also profile components by calling
   `svc.co_case_source_context(..., skip_heavy_context=False)` + the individual
   `list_bcct`/`list_materials` adapter methods directly.
   Secondary: the background preload (`co_case_detail` route → thread →
   `preload_co_case_origin_context`) + 90s TTL cache (`_CO_CASE_SOURCE_CACHE`)
   only help a warm second open; first cold origin still pays full cost.

3. **Origin lock TTL cleanup** (60-min stale lock) — deferred, no code yet.

4. **Customs FX historical backfill** — deferred, no code yet.

5. **Seed missing CO forms** — D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ.

6. **HS↔form coherence + criteria token validation** (MED).

7. **`can_view_client` short→long fallback** — investigated; confirmed **not a
   real prod bug**. UI only generates long-form (`growatt-vn`) client IDs from
   `client["id"]` which comes from DH canonical. 403 only hits typed/bookmarked
   short URLs. `clients` table in prod Postgres is empty — clients loaded live
   from DH. No action needed unless a short-URL entry point is added.

7. **Prod CO↔DH backend auth cutover** — deferred by user (low risk, one
   company only). Cutover steps in previous STATUS.

8. **Open decision:** unique constraint at DB level for new claim identity
   `(client_id, case_id, sheet_product_code, source_row, material_code)`.
   Currently app-only. See `.ai/features/2026-05-29-claim-id-stability.md`.

## Notes for Next AI Session

- **Memory** at `/home/vp/.claude/projects/-home-vp-workspace-client-barry-CO/memory/` — read `MEMORY.md` first.
- **Test on local by default.** Only touch prod when explicitly told.
- **Demo URLs** (in memory, not in repo): `barry-co.tinsu.ai`, `ttdatahub.tinsu.ai`.
- **Prod test account**: `claude-check@local` / `claude-temp-2026`. Short client
  IDs (e.g. `/clients/growatt`) return 403 on prod — use long form `growatt-vn`.
- **Local dev** writes to `/tmp/barry-co-8001.log`.
- **Prod deploy**: SSH `tinsu`, `cd /home/tinsu/co && git pull && docker compose up -d --build app`.
- **DH local**: runs at `:8754` with `--workers 4`, no `--reload`. Restart
  manually if DH schema/code changes.
- **Timing instrumentation** left uncommitted in `app/main.py`:
  `[origin-timing]` log lines in `co_case_light_context`. Remove before
  shipping. Measure first: run dev server, open a case, click Origin cold then
  warm, `grep '[origin-timing]' /tmp/barry-co-8001.log`.
- **`can_view_client`** — explored and confirmed non-issue for prod. UI always
  uses canonical long-form client IDs from DH. Short-form is seed/demo only.
  Do not add fuzzy-match fallback — that trades correctness for convenience.
- **Claim ID migration note**: claims locked before `24d4731` use the old
  positional hash. They're replaced automatically on next lock/release — stock
  math stays correct throughout (re-lock deletes by case+sheet, not by
  claim_id). No manual action needed.
- **BOM workspace cache** (`bom_service.py`): in-process dict, TTL 60s, keyed
  on `(base_url, client_id, token, sorted_product_codes, case_id)`. Preload
  warms it only when `bom_product_codes` is non-empty (i.e. case has products
  and invoice matches). If cold /origin is still slow after source_context
  warms, the bottleneck is likely BOM fetch — consider warming full-client BOM
  unconditionally in preload when case has products.
