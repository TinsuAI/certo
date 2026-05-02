# Project Status

## Current State
- Active branch: `main`.
- `main` is expected to be 26 commits ahead of `origin/main` after the Data Hub BOM consumer commit. Nothing has been pushed.
- CO dev server is running at `http://127.0.0.1:8001`.
- A sibling Data Hub dev server is running at `http://127.0.0.1:8754`.
- Local runtime source mode is now enabled in the ignored runtime config: `DATA_HUB_ENABLED=1`. Data Hub SSO remains active via `CO_AUTH_REQUIRED=1`.
- CO now consumes Data Hub source/master data when source mode is enabled, and local/Postgres/file-backed source stores remain as fallback when source mode is disabled.
- CO now has a Data Hub-backed BOM read path:
  - BOM endpoints are consumed only through `app/data_hub_client.py`.
  - `app/bom_service.py` provides local/Data Hub service boundary.
  - Data Hub mode adapts Data Hub product/version/row payloads into the existing `bom_workspace` shape.
  - Data Hub mode makes canonical BOM UI read-only in CO.
- Shared canonical upload surfaces are hidden or blocked in Data Hub mode:
  - catalog upload/template UI hidden; direct template routes return `409`
  - BCCT upload/template UI hidden; direct template route returns `409`
  - BOM upload/config/template writes blocked or read-only
- C/O case supporting-file upload and C/O case workbook upload remain CO-owned workflow actions and still exist in CO.
- Existing CO-local BOM data was not deleted or migrated. It remains available in local mode for fallback/rollback.
- Pre-existing uncommitted BOM/Data Hub discovery artifacts remain separate from this implementation unless the user asks to commit them:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`

## Recent Changes
- Researched current Data Hub BOM API contract and verified live local Data Hub data:
  - `growatt-vn` has 212 BOM product codes
  - `johnson-vn` has 2 BOM product codes
  - `ui_flat_test` has technical flattening examples
- Added `.ai/features/2026-05-03-co-bom-data-hub-api-port.md` documenting the port plan and Data Hub contract risks.
- Extended `app/data_hub_client.py` with Data Hub BOM methods:
  - list BOM products
  - list product BOM versions
  - get latest/pinned BOM version
  - handle `409 dual_source_variants`
  - submit/fetch BOM proposals
- Added `app/bom_service.py`:
  - local mode delegates to existing `app.bom_store`
  - Data Hub mode builds a read-only `bom_workspace`
  - synthetic aggregate version preserves existing template/case shape
- Wired `app/main.py` to use `bom_service` instead of calling `app.bom_store` directly from routes/context.
- Updated BOM, catalog, catalog table, and BCCT templates so Data Hub-owned upload controls are not shown in Data Hub mode.
- Added Data Hub-mode tests for BOM adapter, service adaptation, read-only BOM page, hidden upload UI, blocked template routes, and blank invoice matching behavior.
- Fixed a real Data Hub-mode C/O case crash: blank invoice numbers no longer call Data Hub `/invoice-matches`, avoiding provider `422`.

## Verification
- `uv run pytest tests/test_data_hub_integration.py -q` passed: 42 tests.
- `uv run pytest tests/test_data_hub_policy.py -q` passed: 3 tests.
- `uv run pytest tests/test_co_demo.py -q -k 'catalog_and_bcct_routes_offer_templates_and_upload_forms or catalog_bom_stock_bcct_are_data_views_and_co_case_is_workflow_entry or bom or upload'` passed: 30 tests.
- `uv run pytest -q` passed: 142 tests.
- Live Data Hub smoke for blank invoice context returned `data-hub []`.
- Live Data Hub BOM smoke for `johnson-vn` returned `data-hub 2 5`.
- `git diff --check` passed.
- `curl http://127.0.0.1:8001/` returned `303` to `/auth/login` when no authenticated browser session was present.
- Existing known issue remains: `npm test` previously failed 3 unrelated legal lookup tests expecting `raw-binary` source links; this session did not rerun Node tests.

## Next Steps
1. Commit this Data Hub BOM consumer/read-only upload UI slice. Push only when the user explicitly asks.
2. Add case-level BOM binding/snapshot persistence for Data Hub `version_id` selections; current slice only adapts the read/view workspace and keeps existing in-memory compatibility shape.
3. Add explicit UI for Data Hub `dual_source_variants` in C/O origin workflow instead of only surfacing the conflict on the BOM page.
4. Decide whether CO should consume Data Hub proposal writes now or wait for provider-side provenance to tag approved proposals as CO-modified/co-proposal instead of default manual-flat metadata.
5. Triage the existing Node legal lookup `raw-binary` failures if a fully green Node suite is required.

## Blockers
- Data Hub proposal provenance should be verified/fixed before CO relies on proposal materialized versions for legal traceability.
- Data Hub BOM endpoints currently have no pagination; acceptable for the current local Growatt-sized smoke, but may need a provider contract extension for larger clients.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese when the user writes Vietnamese. Project docs and handoff artifacts remain English unless client-facing.
- Data Hub mode is currently enabled locally through ignored runtime config. If the app unexpectedly reads local CO-owned data, check the Technical Settings page and `DATA_HUB_ENABLED`.
- Canonical Data Hub-owned source/master data should be changed in Data Hub, not uploaded through CO. CO still owns workflow files, supporting documents, case records, and generated outputs.
- Keep Data Hub API literals inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- The app-level customs FX route remains `/customs-exchange-rates`; it is still local CO reference data for now.
