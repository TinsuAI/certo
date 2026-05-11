# Session Summary: Substitute Modal Search Fallback

Date: 2026-05-12

## What Was Done
- Refreshed project context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Started an auth-disabled local check server on `http://127.0.0.1:8002` for browser reproduction, then stopped it before handoff.
- Reproduced the NVL substitute modal issue:
  - Opening the modal and switching to `Tìm kiếm` worked.
  - Clicking `Tìm` did send `/substitute-candidates?search=...`.
  - The endpoint returned `200`, but `search_results` was empty even for material code `012.0002700` already visible in the sheet.
- Confirmed root cause:
  - Data Hub local returned `500` for `GET /v1/hub/materials?client_id=growatt-vn&limit=...` and `GET /v1/hub/materials/{code}`.
  - Other Data Hub endpoints checked during the session (`source-summary`, `products`, `bcct`) returned `200`.
  - CO caught the catalog search failure and surfaced an empty result set, so the UI appeared broken.
- Implemented a CO-side fallback:
  - `substitute-candidates` now searches current dossier material rows when catalog search fails or returns no matches.
  - results from Data Hub and dossier fallback are de-duped by material code.
  - fallback results include material code, name/description, category, HS, and empty pending stock summary.
  - search empty-state now reports no match or the backend fallback message instead of leaving the stale input prompt.
  - `/substitute-stock` now returns empty stock summaries instead of `500` when its broader source-context fallback hits the broken Data Hub materials endpoint.
- Added regression coverage:
  - `test_origin_sheet_substitute_search_falls_back_to_case_materials_when_catalog_fails`.
- Verification:
  - targeted pytest for substitute candidates/search fallback passed.
  - full `uv run pytest` passed: `211 passed, 1 skipped, 7 warnings in 77.63s`.
  - browser smoke confirmed `Tìm kiếm` renders `012.0002700` and lazy stock returns `200`.
  - focused `git diff --check` passed.

## Decisions Made
- Keep manual search on the existing `/substitute-candidates` CO endpoint; do not add or assume a new Data Hub search endpoint from this repo.
- Use dossier material rows only as a resilience fallback. This keeps the modal usable when Data Hub catalog search is down, but it does not pretend to be full catalog search.
- Do not block candidate rendering on stock lookup. If stock metadata cannot be fetched, return empty stock summaries so the search UI still works.
- Do not commit screenshot directories or `.ai/sister-app-prompts/` scratch artifacts as part of this handoff commit.

## What Didn't Work
- The first browser check showed the tab click itself was fine: it activated `search` and fired the request. The actual failure was empty backend results.
- Direct Data Hub checks with `Bearer dev` showed `/v1/hub/materials` and `/v1/hub/materials/{code}` returning `500`, so fixing only frontend tab behavior would not solve the user-visible failure.
- A second browser smoke initially timed out waiting for an item because the dev server had just reloaded and an earlier request hit a transient 401/500 path. Re-running with detailed logging confirmed the final state: search result renders and `/substitute-stock` returns `200`.

## Open Items
- Fix the Data Hub material catalog endpoint 500s so manual search can find the full catalog, not only materials already in the dossier.
- Add a user-visible "stock unavailable" / retry indicator in substitute rows when lazy stock cannot be loaded; currently empty stock looks like `0 tồn`.
- Continue broader substitute-stock and cross-case ledger browser tests from the previous session summary.
