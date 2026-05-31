# Project Status

## Current State
- Branch `main` at `9064564` — **pushed to `tinsu/main` + deployed (CI/CD green)
  + prod-verified**. Working tree clean.
- **Origin tab full-BCCT pull ELIMINATED — DONE, deployed, prod-verified
  (commits `b3d6083` code + `9064564` docs).** The cold origin tab-load now reads
  stock from the materialized CO-stock snapshot (same source `/calculate` uses) +
  a narrow export invoice_matches fetch, instead of the ~40s full `list_bcct`
  (65k rows for Johnson). Real-Johnson parity (local DH): **invoice_matches
  byte-identical**, stock material_code coverage identical (8 660),
  `origin_build_signature` stable across reloads. Local: origin source-context
  **~60s → ~0.9s warm / ~8s cold** (one-time delta refresh). **Prod benchmark
  (johnson-vn, throwaway case, created→measured→deleted): cold `/origin`
  **1.47s** (warm 1.64s)** — faster than local cold because the nightly stack
  refresh keeps the prod snapshot fresh, skipping the delta-refresh. Prod
  snapshot present (60 173 rows). BOM workspace (~22s) is now the dominant origin
  cost (separate task).
- Session summaries:
  `.ai/sessions/2026-05-31-origin-narrow-bcct-tdd-ship.md` (latest — TDD+ship),
  `.ai/sessions/2026-05-31-origin-bcct-elimination-discovery.md` (design),
  `.ai/sessions/2026-05-31-case-detail-perf-fix-and-dh-guard.md`.
- Local suite **395 passed + 8 skipped** (file-store/CI mode; the +1 skip is the
  opt-in real-DH origin parity e2e).
- **Case detail (shipment) load fix DONE, deployed, prod-verified.** Local DH
  E2E (johnson-vn, 12.5k materials / 66k BCCT): origin/old path 39.7s → shipment
  light 0.03s, 82 → 2-3 round trips, invoice_matches parity preserved. Prod
  benchmark (Bearer JWT, `johnson-vn / co-case-0605189d5eea`): shipment tab
  ~1.5–3.6s vs ~21s baseline (~7–10x).
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

## Recent Changes (2026-05-31 session)

| Commit | Topic |
|---|---|
| `b3d6083` | perf(origin): converge cold origin tab-load onto the CO-stock snapshot + narrow export invoice_matches; drop the ~40s full `list_bcct` pull. New `origin_source_context` (main.py) + `DataHubPortfolioService.origin_invoice_matches`; DH-mode guard (file-store/test falls back to in-memory heavy path); cache-warm gated on `material_rows`. 6 unit tests + 1 opt-in real-DH parity e2e. **Local only — not pushed/deployed.** |

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

> **▶ BOM workspace perf — DONE, deployed, prod-verified** (commits `2c0ff21` code
> + `3c077ea`/this-doc; CI/CD run 26713547506 green: tests+docker+deploy+nightly
> refresh). Prod benchmark (johnson-vn / `co-case-0605189d5eea`, 2 products
> `PV00.0048500`+`PV01.0117600`, Bearer JWT): `/origin` **200, byte-identical**
> output across runs, no 401 → **contextvar token propagation confirmed under prod
> live auth** (the key risk; local DH had auth off). Cold ~2.9s, warm ~1.0s. Timing
> varies run-to-run (2.9 / 1.0 / 3.2s) because the BOM cache is **in-process per
> worker** and prod runs multiple workers → a cold worker re-pays until warmed (not a
> bug). NOTE: this case is only 2 products, so it proves correctness/no-regression,
> not a heavy speedup; the speedup characterization is the local N=50 run below.
> Parallelized the sequential per-product DH fetch in `_build_workspace`
> (bom_service.py). New `_fetch_product_results` runs each product's
> `_build_product_result` concurrently via `ThreadPoolExecutor`
> (`BOM_FETCH_MAX_WORKERS=8`), propagating `CURRENT_DATA_HUB_TOKEN` with a fresh
> `copy_context()` per task (worker threads don't inherit contextvars → would 401
> otherwise). Assembly stays in product order; final sort makes output fully
> order-independent. Single-product fast path skips the executor.
> - **Parity: byte-identical** (local DH, real Johnson products N=20/40: product_versions,
>   latest_rows count, aggregate version_hash, variant_conflicts, dh_picker_filter all
>   equal sequential). Live contextvar propagation verified (workers=8, no 401).
> - **Speedup ~2.3–2.6x local** (N=20: 0.30s→0.13s; N=40: 0.66s→0.26s). Local DH is
>   co-located so per-product latency is tiny → the win scales with latency; prod
>   (network round-trips) should see a larger speedup. The discovery-era ~22s figure
>   predates the BCCT-pull elimination and a faster local DH.
> - Tests: `tests/test_bom_workspace_parallel.py` (4: concurrency-barrier proof,
>   token contextvar propagation, output determinism vs fetch order, variant-conflict
>   under parallel). Full suite **399 passed + 8 skipped** (file-store mode).
> - Decision: stayed with parallel client-side fetch (A); confirmed NO multi-product
>   batch DH endpoint exists (all BOM paths are single `{product_code}`), so a batch
>   approach would need a DH contract change. Materialize-BOM (C) not needed.
> - **Next:** commit + push (CI/CD deploy) + prod benchmark on product-heavy case
>   `co-case-0605189d5eea` — **pending user go-ahead** (not yet committed).

1. **Case detail load (shipment tab) ~21s — DONE, deployed, prod-verified.**
   `skip_heavy_context` on `co_case_source_context` (commit `d28e237`, deployed
   via CI run `aab0957`). Prod benchmark (`johnson-vn / co-case-0605189d5eea`,
   Bearer JWT for `claude-check@local`): shipment tab **~1.5–3.6s** vs ~21s
   baseline (~7–10x). invoice_matches parity preserved (local E2E: 39.7s→0.03s).

2. **Origin tab full-BCCT pull — DONE, deployed, prod-verified (commits
   `b3d6083` code + `9064564` docs).** Implemented per brief
   `.ai/features/2026-05-31-origin-narrow-bcct-fetch.md`. Cold origin tab-load now
   reads stock from the materialized `co_stock_rows` snapshot + a narrow export
   invoice_matches fetch; the ~40s full `list_bcct` (65 846 rows) is gone.
   Real-Johnson parity: invoice_matches byte-identical, stock coverage identical,
   `origin_build_signature` stable. Code: `origin_source_context` (main.py) +
   `DataHubPortfolioService.origin_invoice_matches`; wired into
   `co_case_light_context` cold origin branch with a DH-mode guard.
   - **Deployed via CI/CD** (push `tinsu/main` → tests+docker+deploy all green).
     **Prod benchmark** (johnson-vn, throwaway case created→measured→deleted):
     cold `/origin` **1.47s** / warm 1.64s vs ~60s baseline. Local: ~0.9s warm /
     ~8s cold (local snapshot was stale → one-time delta refresh; prod's nightly
     refresh keeps it fresh, so prod cold skips that). Prod snapshot present
     (60 173 rows).
   - **Prod delete needs a privileged role**: `claude-check@local` is NOT in
     `co_case_delete_roles` → `/delete` returns 403. To remove a prod case, use
     `delete_case_record` inside container `co-app-1` via SSH `tinsu`.
   - **DH `/v1/hub/bcct` filters on singular `declaration_no`** — plural
     `declaration_nos` silently ignored; export-decl fetch loops per declaration.
     Memory: `dh-bcct-declaration-filter-singular`.
   - **Freshness (scheduled refresh) still deferred** — refresh-on-access already
     lives in `_calculate_stock_rows_from_snapshot`. Memory:
     `origin-costock-freshness-deferred`.
   - **Next origin bottleneck = BOM workspace (~22s)** — separate task (see Notes).
   - Local invoice-only test case `co-case-ec000d03522e` (invoice `VNG25120047`).
     Re-run parity: `set -a; . ./.env; set +a; RUN_ORIGIN_PARITY_E2E=1 PYTHONPATH=.
     .venv/bin/python -m pytest tests/test_origin_narrow_source_context.py -k
     parity_e2e -q`.

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
- **Timing instrumentation** — already clean; no `[origin-timing]` lines remain
  in `app/main.py` (verified 2026-05-31).
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
