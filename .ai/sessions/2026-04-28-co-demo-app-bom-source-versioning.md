# Session Summary: CO Demo App, BOM, Catalog, and BCCT Versioning

## What Was Done
- Built a working FastAPI/Jinja C/O demo app with a BCQT-System-inspired client workspace.
- Split the client workspace into separate views for overview, customs catalogs, BOM, C/O stock, BCCT, and C/O case.
- Added seeded data for the initial simple case where customs code and internal code are treated as the same code.
- Added workbook upload and parsing for C/O input/evidence files, direct BOM files, technical BOM files, DS NVL, DS SP, and BCCT.
- Added file-backed stores for BOM and source modules under local-only `data/local/...`, including raw upload retention, snapshots, versions, audit events, and lock/atomic-write handling.
- Implemented BOM versioning at aggregate level and per-product level, so a new technical BOM for one product creates a new product BOM version and a new aggregate BOM version.
- Implemented source-module semantics:
  - DS NVL and DS SP are reference catalogs.
  - BCCT is transaction evidence.
  - Technical BOM is engineering/product-structure evidence.
- Implemented BCCT re-upload behavior:
  - New transaction keys are added.
  - Identical rows are no-ops.
  - Same-key changed rows become correction candidates.
  - Missing old rows are not deleted.
  - Import rows are the only source for C/O stock.
- Added manual Excel test files under `data/local/manual-test-files/` and ran a Playwright smoke test uploading real files through the app.
- Added a light/dark theme toggle in the top navigation, modeled after BCQT-System but persisted with a lightweight cookie instead of session middleware.
- Added tests for the app, workbook round trips, BOM behavior, catalog/BCCT upload semantics, C/O stock derivation, source snapshots, and theme persistence.

## Decisions Made
- Use FastAPI/Jinja for the first demo shell. This is a demo architecture decision, not a final production decision for database, auth, deployment, or API style.
- Keep runtime uploaded data in ignored local storage under `data/local/...` for now, rather than introducing a database before the workflow is validated.
- Treat customs catalogs, BCCT, and technical BOM as separate source families with different semantics; do not merge them into one canonical table.
- For BCCT transaction identity, use `direction + declaration_no + line_no + item_code` as the current recommended key. Coverage period remains metadata, not identity.
- For catalog full uploads, omitted existing codes become `inactive_pending_review` rather than being deleted.
- For catalog partial uploads, omitted codes remain unchanged.
- For unit handling, aliases such as `PCS` and `PCE` normalize to the same unit; a real unit change such as `PCS -> KG` is a correction candidate.
- For theme persistence, use a `co_theme` cookie because the CO demo app does not yet have BCQT-System's session/auth middleware.

## What Didn't Work
- Playwright was not installed in the repo environment, so the browser smoke test used `uv run --with playwright` with the cached Chromium browser.
- A full production-style stack was intentionally deferred because the user wanted a working interactive demo before locking architecture.

## Open Items
- Add review/accept UI for BCCT correction candidates.
- Add review UI for catalog rows in `inactive_pending_review`.
- Add C/O case UX for choosing specific BOM aggregate/product versions.
- Confirm whether declaration number alone is unique enough across customs office/type/company contexts.
- Confirm how stable `line_no` is across ECUS/BCCT exports.
- Confirm the business rule for corrections that affect already-issued C/O dossiers.
