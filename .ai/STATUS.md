# Project Status

## Current State
- The repo now has a working FastAPI/Jinja C/O demo app for agency staff under `app/`, with a BCQT-System-inspired UI and client-specific workspace.
- The demo supports these views per client: overview, customs catalogs, BOM, C/O stock, BCCT, and C/O case.
- The app can upload and version DS NVL, DS SP, BCCT, direct BOM workbooks, and technical BOM workbooks. Runtime data is stored under local-only `data/local/...`.
- Tests cover origin calculations, workbook round trips, BOM versioning, catalog/BCCT upload semantics, C/O stock derivation, and theme persistence.

## Recent Changes
- Added the FastAPI app, templates, CSS, workbook I/O, origin logic, seeded demo data, source-module store, and BOM store.
- Added BOM versioning at both aggregate and per-product levels, including technical BOM parsing lanes for Growatt-style and Johnson/SAP-style inputs.
- Added DS NVL/DS SP upload logic with full-catalog vs partial-update semantics.
- Added BCCT upload logic where import/export rows are transaction evidence, re-uploads add missing rows, same-key changes create correction candidates, and C/O stock derives only from reviewed import rows.
- Added light/dark theme toggle in the top navigation, persisted by `co_theme` cookie.
- Added discovery/implementation docs for BOM and source-module handling.

## Next Steps
- Manually validate the demo flow with the generated Excel files under `data/local/manual-test-files/`: upload catalogs, BCCT, BOM, then inspect C/O stock and C/O case snapshots.
- Add UI actions for reviewing/accepting BCCT correction candidates and catalog inactive-pending-review rows.
- Add a BOM version picker/selector flow in the C/O case UI once the intended operator workflow is confirmed.
- Confirm remaining domain questions: exact customs transaction-key scope, line number stability across exports, and how to handle corrections after a C/O has already been issued.

## Notes for Next AI Session
- Start the app with `npm run co:serve`; the current dev server has been running on `http://127.0.0.1:8001/clients`.
- `data/` is intentionally ignored and local-only. Do not commit generated manual test files, screenshots, raw uploads, or source-module state.
- Use `uv run pytest tests/test_co_demo.py -q` for the current Python app test suite.
- User preference: respond in Vietnamese when the user writes Vietnamese, and keep docs/artifacts in English unless client-facing.
