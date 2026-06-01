# 2026-05-13 Origin Workbook DB Save Hardening

## What Was Done
- Hardened the C/O origin workbook flow across Load BOM, sheet edit, save, and lock/reopen behavior.
- Added compact workbook JSON payload handling so autosave/action/save requests carry:
  - `origin_product_order`
  - all `products`
  - `bom_product_artifact_overrides`
  - `origin_sheet_states` for every sheet
  - `expected_revision`
- Changed `Lưu bảng kê` to save the current sheet's NVL edits while also merging the full workbook snapshot first, so workbook-level state is not dropped.
- Implemented server-side recompute after sheet edits:
  - replacement, add, delete, and norm edits are persisted as `origin_sheet_states[product_code].material_overrides`
  - current sheet is recalculated from those overrides
  - later sheets are marked stale
- Added live client-side allocation rebuilding for affected NVL codes, so replacing NVL or changing norm refreshes child stock rows immediately instead of waiting for a full Load BOM.
- Fixed the replacement bug where parent row changed but child stock rows still belonged to the old NVL.
- Added dirty sheet history with `Lùi` / `Tiến`, and a batched save banner for client-side edits.
- Fixed `Lưu bảng kê` stuck states:
  - added a 60s abort controller
  - restored button state on error/timeout
  - added an in-flight guard for double-clicks
- Fixed `Load BOM vào Bảng kê` loading feedback:
  - sheet-level loading banner appears immediately
  - global progress stays active until response text is parsed and shell replacement finishes
- Fixed a URL/state bug after POST actions:
  - POST action responses no longer replace browser history with `/origin/sheet/.../calculate`
  - save now redirects to canonical `/clients/.../co-case/.../origin`
  - this prevents `GET /origin/sheet/.../calculate` returning `405 Method Not Allowed` after save/reload
- Fixed allocation child-row toggle after AJAX shell replacement by moving `data-allocation-toggle` initialization into `refreshCaseShellInteractions()`.
- Fixed local material search for seed catalog lists in `PortfolioService.search_materials`.
- Switched the local CO dev environment to DB-backed state:
  - created ignored local `.env` with `BARRY_DATABASE_URL=postgresql:///barry_co?host=/var/run/postgresql`
  - updated `npm run co:serve` to source `.env` before starting uvicorn
  - ran migrations and imported app/workflow state
  - rebuilt source indexes for `growatt`, `johnson`, and `do-thanh`
- Added discovery note `.ai/features/2026-05-12-origin-sheet-live-allocation/brief.md`.
- Added regression tests for:
  - compact workbook payloads
  - autosave preserving all sheet states
  - sheet save recompute and workbook merge
  - allocation toggle initialization
  - local material search list support
  - save URL/double-click guard markers in rendered page

## Decisions Made
- Keep workbook persistence as structured case JSON in Postgres, not as an Excel-like cell matrix.
- Treat `Lưu bảng kê` as current-sheet NVL edit persistence plus workbook metadata merge, not as a full workbook material-edit save.
- Treat `Chốt` as the official cross-case stock claim event. Load/save/calculate remain internal workbook operations; only lock writes `co_stock_claims`.
- Use sparse row-index overrides (`material_overrides`) for sheet edits to avoid rewriting full BOM rows in state.
- Keep live allocation client-side scoped to affected material codes, while server save still recomputes the whole current sheet for persisted correctness.
- Use canonical `/origin` as the browser URL after sheet save and after POST actions; action endpoints should not become browser history locations.
- Use the existing Postgres schema (`barry_co`, schema `co`) for CO dev state rather than introducing another database or JSON ledger.

## What Didn't Work
- Browser save after Load BOM exposed that `replaceCaseShellFromResponse()` was replacing browser history with the action endpoint URL. A later save `reload()` then issued `GET /calculate`, causing `405 Method Not Allowed`.
- Starting a second CO dev server on `8004` helped earlier browser checks but created confusion. It was shut down; keep one CO server on `8001`.
- Running CO without `BARRY_DATABASE_URL` left `co_stock_claims` unavailable; locks no-oped for official stock ledger state even though BCCT stock rows existed locally.
- `uv run` does not auto-load `.env`; the dev script had to source `.env` explicitly.
- Browser checks against existing dev cases sometimes lacked allocation rows or enabled Load BOM buttons, so endpoint/template tests remained important for regression coverage.
- `npm test` still fails on unrelated legal lookup tests expecting `raw-binary` links.

## Open Items
- Browser-test cross-case stock ledger with DB enabled:
  - lock case A and verify case B sees reduced remaining stock
  - reopen case A and verify stock is restored
  - check concurrent lock/overclaim behavior
- Verify Data Hub `bcct/by-codes` endpoint availability and performance before relying on narrow stock lookup for large Johnson sheets.
- Confirm whether Data Hub material catalog 500s still occur for `growatt-vn`/`johnson-vn`; CO has fallbacks but full substitute search depends on Data Hub.
- Clean up unused client-side replacement allocation helper code if it remains unused after live allocator integration.
- Fix unrelated Node legal tests around missing `raw-binary` source links.
- Continue NVL origin classification config / Data Hub evidence source backlog item.
