# Session Summary: Substitute Modal Tabs And Data Hub UOM Contract

Date: 2026-05-11

## What Was Done
- Refreshed project context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Confirmed CO dev server and local Data Hub were already running:
  - CO `http://127.0.0.1:8001/healthz` returned `200`.
  - Data Hub `http://127.0.0.1:8754/healthz` returned `200` earlier in the session.
- Reviewed backlog and current blockers. Highest-priority open work remains browser-testing the cross-case stock ledger and verifying Data Hub `bcct/by-codes` availability for substitute-stock performance.
- Split the NVL substitute modal into two tabs:
  - `Khuyến nghị`: recommendations from Data Hub substitute endpoint or CO HS-prefix fallback.
  - `Tìm kiếm`: manual material search with its own input and button.
- Refactored substitute modal JS:
  - Added tab state and tab panel toggling.
  - Replaced mixed `fetchCandidates(search)` behavior with `fetchRecommendations()` and `fetchSearch()`.
  - Kept lazy stock merge shared through `mergeLazyStock()`.
  - Existing material replacement opens on `Khuyến nghị`; adding a new material row opens on `Tìm kiếm`.
- Confirmed Data Hub catalog contract change by reading Data Hub commits:
  - `6a1b47a` migration 063 consolidates `materials.unit` into `uom`.
  - `42decc7` updates pipeline/read API and keeps `unit` only as deprecated alias.
  - `f64b500` updates tests/fixtures around `uom`.
- Migrated CO Hub material/product normalization:
  - `normalize_material_row()` now returns `uom` and removes `unit` from normalized material rows.
  - `normalize_product_row()` now returns `uom` and removes `unit` from normalized product rows.
  - Both accept `row.get("uom") or row.get("unit", "")` only at the adapter boundary.
- Updated downstream Data Hub catalog consumption:
  - Data Hub-backed catalog table view maps the `ĐVT` column/filter/summary to `uom`.
  - HQ workbook header cell `L9` prefers `product.uom`, falling back to internal `unit`/`export_unit`.
- Added regression coverage:
  - `test_data_hub_material_product_rows_consume_canonical_uom_only` verifies `uom`-only Hub material/product rows flow through normalize, source workspace, and search without `unit`.
- Verification performed:
  - Substitute modal targeted tests passed.
  - Data Hub uom targeted test passed.
  - Full CO regression suite passed: `uv run pytest` -> `210 passed, 1 skipped, 7 warnings`.
  - `git diff --check` passed for touched files.

## Decisions Made
- Do not rename CO internal `unit` fields globally. `unit` remains correct for BCCT/customs declarations, source-store rows, case product state, and local catalog paths.
- Treat `uom` as canonical only for the Data Hub material/product interface. The adapter accepts the deprecated Hub `unit` alias as a fallback during the grace window, but normalized CO Hub rows no longer expose `unit`.
- Keep Data Hub-backed catalog display labels as `ĐVT`, but map the data key to `uom` when `source_backend == "data-hub"`.
- Do not add a new CO endpoint for substitute search. Existing `/substitute-candidates` already supports search-only calls; the UI separation was enough.

## What Didn't Work
- The first targeted pytest command used a guessed test name (`test_data_hub_portfolio_service_uses_indexed_invoice_matches`) that does not exist; pytest reported no match. Reran with the correct test names and they passed.
- A broad grep for `"unit"` produces many matches that must not be renamed. Most are BCCT/customs/internal CO fields, not Hub material/product contract fields.
- `git diff --stat` includes many changes from earlier sessions because the working tree was already dirty. Treat this session's new work as the substitute modal tab split plus Data Hub `uom` contract migration.

## Open Items
- Browser-test substitute modal tabs manually in an authenticated case, including:
  - Existing NVL opens `Khuyến nghị`.
  - `Tìm kiếm` tab does search-only request and applies a material correctly.
  - Add-row path opens directly on `Tìm kiếm`.
- Browser-test the cross-case stock ledger end-to-end.
- Verify whether Data Hub `bcct/by-codes` provider endpoint is live; if not, keep the API request open as the performance blocker for first substitute-stock loads.
- Revisit `/lock` persisted-state handling so allocation lines are not vulnerable to form-rebuild wipe.
- Decide commit scope for the large dirty tree and unrelated artifacts before committing.
