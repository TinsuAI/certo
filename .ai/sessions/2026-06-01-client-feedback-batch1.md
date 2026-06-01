# Session 2026-06-01 — Client feedback batch 1 (delete dossier + substitute stock)

## What Was Done

Triaged a 6-item client feedback PDF (`HIỆN TRẠNG BARRY CO`) against the code, then
implemented + prod-verified the two highest-value items.

**Triage** (full table in `.ai/features/2026-06-01-client-feedback-batch1.md`): all 6 valid.
1. No delete-dossier — perception bug (feature gated to dev/admin; testers are manager).
2. "mở" load slow — already fixed prior sessions.
3. Substitute sometimes errors / no suggestion — flaky DH BCCT dependency.
4. Substitute suggestions not appropriate — DH ranking quality (cross-team).
5. Want multiple filters at once (code + name).
6. Want multi-row select for bulk delete.

**#1 — manager delete (commit `e296267`):** added `manager` to
`DEFAULT_CO_CASE_DELETE_ROLES` in `data_hub_settings.py:13`. Unit test
`test_can_delete_co_cases_allows_manager_by_default`. The delete route/store/guards
(`co_case_store.delete_case_record`, release-claims confirm, block-when-completed/locked)
were already present — only the role gate excluded managers.

**#3 — substitute stock from snapshot (commit `3af5914`):** reworked
`co_case_origin_sheet_substitute_stock` (`main.py` ~7135) to read candidate tồn **only**
from the materialized CO-stock snapshot (`co_stock_materializer.read_co_stock_rows_cached`),
filtered by requested codes via `co_stock_key_candidates`, then `case_allocation_pool`.
Removed the `list_bcct_by_codes` (DH BCCT) primary path AND the `co_case_source_context_cached`
fallback. Added `stock_refreshed_at` to the JSON response and a freshness chip in the
substitute modal (`co_case.html`: toolbar `[data-origin-substitute-freshness]` +
`updateFreshness()` called inside `mergeLazyStock`). Test
`test_substitute_stock_reads_materialized_snapshot_not_bcct` monkeypatches
`list_bcct_by_codes` to raise, proving it's never called.

**Verification:** local suite 405 passed + 8 skipped. Playwright browser test local
(growatt-vn) + prod (https://barry-co.tinsu.ai, manager account, auth ON). Prod confirmed:
manager sees delete button; substitute modal shows real candidates + tồn + ΔLVC +
freshness chip, 0 console errors. Screenshots in
`.ai/screenshots/client-feedback-batch1/` (local 01/03, prod-01/prod-03). Committed +
pushed `tinsu/main` → CI green → deployed to co-app-1 @ `013750d`.

## Decisions Made

- **#3 reframed mid-session by user insight.** Initial plan was "retry DH + never-empty".
  User pointed out the what-if (đủ tồn / ΔLVC) is already in the modal and only needs CO
  stock, not BCCT. Correct fix = read the materialized snapshot, not re-derive from BCCT.
- **No fallback path.** User: "bỏ đường file-store đi — nó giải quyết được gì đâu". Removed
  both the file-store and the heavy-live-DH fallback. Snapshot is the single source of
  truth (no-silent-local-fallback rule). A code absent from the snapshot = no tồn (honest
  empty), not an error or a 40s DH pull.
- **Freshness handling = "snapshot + show refresh marker"** (user choice), not auto-refresh
  and not a live by-codes safety net. Used `last_refresh_at` (cheap, no BCCT); skipped
  full `compute_sync_status` because it needs a live BCCT count.
- **#1 = code default change**, not env-only, since the business decision (managers can
  delete) should hold across deployments. Guards still protect.
- **#4 → Data Hub API request** (user choice), since ranking quality is DH-owned. Deferred:
  needs concrete bad examples from the client first.

## What Didn't Work / Time Sinks

- **Local DB client-id form confusion.** The app reads co_stock under the URL client_id;
  real data is stored under the **`-vn` forms** (`growatt-vn`/`johnson-vn`), while short
  forms `growatt`/`johnson` carry only a single DEMO seed row. First browser attempts used
  `growatt` and saw `DEMO-NPL-001` only. Switching to `growatt-vn` surfaced the 38k real
  rows. (Also: ad-hoc `psql` to the same connection string hit a *different* cluster than
  the app's psycopg — trust the app connection.)
- **Origin sheet not at the bare case URL.** Substitute triggers live only at the
  `/origin` sub-path; the case detail is an SPA with per-step rendering
  (`co_case_active_step == "origin"`). Playwright on the bare URL saw 0 triggers.
- **Playwright module resolution.** Not in repo node_modules; needed `NODE_PATH` pointing
  at the npx cache `node_modules`. `page.evaluate` takes one arg (wrap multiples).
- All of the above are now captured in memory `browser-test-recipe.md`.

## Open Items

- **#5, #6, #4, #2-confirm** deferred to next session (see STATUS Next Steps). #4 and #6
  need client input first (bad-example codes; which table for bulk select).
- Freshness chip date format renders as `DD-MM` (vi-VN `toLocaleString`) — cosmetic, left
  as-is.
- The materialized snapshot can lag BCCT; freshness chip surfaces this but there is no
  auto-refresh on case open (parked under "Origin CO-stock freshness (deferred)").
