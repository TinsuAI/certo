# Project Status

## Current State
- Branch `main` at `013750d` — pushed to `tinsu/main` + **deployed (CI/CD green, co-app-1 @ `013750d`)**.
  Working tree clean. Local suite **405 passed + 8 skipped** (file-store/CI mode).
- **Client feedback batch 1 — #1 + #3 DONE, prod-verified (2026-06-01).** Triage of the
  6-item client PDF feedback is in `.ai/features/2026-06-01-client-feedback-batch1.md`.
  - **#1 Delete dossier visible to managers** — feature already existed but was gated to
    `dev`/`admin`; client testers are `manager` → couldn't see it. Added `manager` to
    `DEFAULT_CO_CASE_DELETE_ROLES` (`data_hub_settings.py:13`). Existing guards
    (release-claims confirm, block-when-completed/locked) unchanged. **Prod-verified**
    with the real manager account (auth ON): manager now sees the "Xoá" button.
  - **#3 Substitute "no suggestion / errors"** — root cause was deeper than retry-DH:
    `/substitute-stock` re-derived CO stock from BCCT live via `list_bcct_by_codes` (a
    flaky Data Hub round-trip that intermittently blanked suggestions). The modal's
    what-if (đủ tồn? / ΔLVC, computed client-side in `co_case.html`
    `computeFeasibility`/`renderFeasibilityCell`) only needs CO stock lots. Reworked the
    endpoint to read **solely from the materialized CO-stock snapshot**
    (`co_stock_materializer.read_co_stock_rows_cached`), case-allocated — no BCCT, no
    silent file-store/heavy-DH fallback (per no-silent-local-fallback rule). Response now
    carries `stock_refreshed_at`; the modal shows a freshness chip ("Tồn cập nhật HH:MM
    DD-MM"). **Prod-verified** (johnson-vn mã 0000081548 → 10 DH candidates, real lots +
    ΔLVC +0.17%→76.99%; growatt-vn DIENTRO.CHIP 868 lô/25M tồn; 0 console errors).
    Screenshots in `.ai/screenshots/client-feedback-batch1/`.
- **Still current from prior sessions:** DH↔CO internal-network + JWKS cutover (prod);
  BOM workspace batch endpoint + parallel fetch; origin narrow-BCCT; case-detail
  `skip_heavy_context`; no-silent-local-fallback; claim-ID stability.

## Recent Changes (2026-06-01 session)

Full detail: `.ai/sessions/2026-06-01-client-feedback-batch1.md`.

| Commit | Topic |
|---|---|
| `013750d` | docs: triage + fix plan for client feedback batch 1 |
| `3af5914` | fix(substitute): source candidate tồn from materialized CO-stock snapshot |
| `e296267` | feat(co-case): allow manager role to delete CO dossiers |

New tests: `test_can_delete_co_cases_allows_manager_by_default`
(`tests/test_data_hub_integration.py`), `test_substitute_stock_reads_materialized_snapshot_not_bcct`
(`tests/test_co_demo.py`, asserts BCCT is never called).

## Next Steps (priority order)

**Client feedback batch 1 — remaining (plan: `.ai/features/2026-06-01-client-feedback-batch1.md`):**
1. **#2 "mở" load lâu** — already fixed in prior sessions (skip_heavy_context, BOM batch,
   internal network). No code; just **confirm with client** the current build feels fast,
   and if not, capture which step + client + timing before any further work.
2. **#5 Multi-filter (mã + tên cùng lúc)** — extend the shared table component
   (`table_view.py` + `_advanced_table.html`) to support free-text `kind:"text"` filters
   per field alongside the existing select filters. Benefits all 5 tables. Effort M.
3. **#4 Substitute "chưa phù hợp"** — chiefly DH ranking quality. User decided: **file a
   Data Hub API request** (`.ai/api-requests/2026-06-01-substitute-ranking-quality.md`
   from the template) — needs 3-5 concrete bad-example material codes **collected from the
   client first**. Optionally also improve CO heuristic fallback (`main.py:7218+`) beyond
   HS-prefix. Effort M + cross-team.
4. **#6 Multi-select + bulk action (xóa hàng loạt)** — add checkbox column + select-all +
   bulk-action bar to `_advanced_table.html` (per-table opt-in). First action = bulk
   delete looping the guarded single-delete. **Needs client confirmation on which table.**
   Effort M-L.

**Older deferred (pre-feedback):**
5. Origin lock TTL cleanup (60-min stale lock).
6. Customs FX historical backfill.
7. Seed missing CO forms (D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ).
8. HS↔form coherence + criteria token validation (MED).
9. Claim-identity DB unique constraint (app-only today; see
   `.ai/features/2026-05-29-claim-id-stability.md`).

## Notes for Next AI Session
- **Browser testing recipe** is in memory `browser-test-recipe.md`: real data lives under
  client **`-vn` forms** (`growatt-vn` ≈38k co_stock rows, `johnson-vn` ≈60k); short forms
  `growatt`/`johnson` only have DEMO seed (1 row). Origin sheet renders at the **`/origin`
  sub-path** (case detail is an SPA with workflow steps). Substitute freshness chip only
  shows when a material has candidates.
- **Playwright**: not in repo node_modules; run with
  `PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright | head -1)"); NODE_PATH="$PWDIR" node script.js`.
- Local dev server runs on `:8001` (`npm run co:serve`), `CO_AUTH_REQUIRED=0` (role gating
  not testable locally — use unit tests or prod with the manager account).
- Local `barry_co` Postgres is reachable two ways that DISAGREE: the app/psycopg sees the
  demo-seed DB; a stray `psql` to the same string can hit a different cluster — trust the
  app's connection, not ad-hoc psql.
- `#3` snapshot path only activates in Postgres mode (`_store_available()` =
  `bool(BARRY_DATABASE_URL)`); both local and prod satisfy this.
