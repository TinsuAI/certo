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
| `ad17bb3` | perf: preload in background thread (necessary but insufficient — see perf note below) |

## Recent Changes (2026-05-29/30 session)

| Commit | Topic |
|---|---|
| `2b9c535` | Guard `data_hub_target_url` against empty deep-link — only emit when a real DH page exists; 4 templates wrap the "Mở DH" button in `{% if data_hub_target_url %}` |
| `24d4731` | **Claim ID stability** — `claim_id_for` keyed on `material_code` (not BOM position); `_build_claim_rows` sums qty on collision (fixes latent under-claim). 6 DB-free unit tests + 3 Postgres-gated e2e tests pass. Brief: `.ai/features/2026-05-29-claim-id-stability.md` |
| `cdbeef2` | STATUS update |
| `5d34ed8` | CI: nightly CO stack refresh after prod deploy (on-merge trigger) — user committed separately |
| `ea25b36` | CI: self-pull tinsu-deploy before nightly refresh — user committed separately |

## Next Steps

1. **Case detail load ~21s — root cause found, fix NOT done yet (HIGH PRIORITY)**

   **Root cause:** `co_case_source_context` (called by `co_case_light_context`
   for every step including shipment) fetches `list_materials` + `list_bcct`
   (65k rows for Johnson) even when rendering the shipment tab, which only
   needs `source_summary` + `invoice_matches`.

   **What was tried (partial fix, `ad17bb3`):** moved `preload_co_case_origin_context`
   to a background thread — necessary, but the **shipment tab render itself**
   still calls `co_case_source_context` synchronously. Measured: 21s before
   and after the background fix on prod (Johnson, case with invoice_no).

   **Why shipment tab triggers full BCCT fetch:**
   `co_case_source_context` short-circuits (returns only `source_summary`)
   only when case has NO `invoice_no`, no `export_declaration_nos`, AND no
   `products` (line 628 in `data_hub_client.py`). Johnson cases always have
   an `invoice_no` → triggers full `list_materials` + `list_bcct` pagination
   even though shipment tab doesn't use `material_rows` or `stock_rows`.

   **Fix to implement next session:**
   In `co_case_light_context` (or `co_case_source_context`), skip
   `list_materials` + `list_bcct` pagination when the caller only needs
   `source_summary` + `invoice_matches` (i.e. non-origin steps). The
   `invoice_matches` DH endpoint (`/v1/hub/bcct/invoice-matches`) is already
   a lightweight dedicated call — only the BCCT enrichment
   (`enrich_invoice_matches_with_bcct`) and stock rows need the full paginate.

   Options:
   - **A (targeted):** add `skip_heavy_context: bool = False` param to
     `co_case_source_context`; when True, skip `list_materials`/`list_bcct`,
     return bare `invoice_matches` from the lightweight endpoint only.
     Pass `skip_heavy_context=True` for all steps except `origin`.
   - **B (lazy):** split `co_case_light_context` into two phases: fast
     (source_summary + invoice_matches) always, heavy (materials + bcct) only
     on demand. More invasive but cleaner long-term.
   Option A is lower-risk; go with A unless B is obviously better on review.

   **Test case on prod:** `johnson-vn / co-case-0605189d5eea` (invoice_no
   `VNG26050002`, 0 products). Snapshot was cleared for benchmark — will
   re-populate automatically on next load after fix. Benchmark baseline: 21s.

2. **Origin lock TTL cleanup** (60-min stale lock) — deferred, no code yet.

3. **Customs FX historical backfill** — deferred, no code yet.

4. **Seed missing CO forms** — D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ.

5. **HS↔form coherence + criteria token validation** (MED).

6. **`can_view_client` short→long fallback** — investigated; confirmed **not a
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
