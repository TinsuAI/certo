# Session: Postgres State Migration

## What Was Done
- Ported app-level state from JSON/local files to Postgres when `BARRY_DATABASE_URL` is set.
- Added the portfolio boundary and Postgres app-state store:
  - `app/portfolio.py`
  - `app/app_state_store.py`
  - `app/client_registry.py`
  - `app/database.py`
  - `db/migrations/002_application_core.sql`
- Extended source indexes from read models into a Postgres-backed source workspace:
  - current catalog rows
  - BCCT rows and invoice lookup index
  - C/O stock rows
  - upload/raw-file metadata
  - snapshot/version/audit metadata
  - parsed snapshot rows and historical version rows
- Added direct Postgres source upload writes in `app/source_postgres_store.py`.
- Standardized source upload file metadata in `app/source_store.py`.
- Added `app/workflow_state_store.py` and migration `005_workflow_state.sql` for:
  - BOM state, uploads, snapshots, snapshot rows
  - BOM product versions and product-version rows
  - BOM aggregate versions and aggregate-version rows
  - BOM audit events
  - C/O case state, case records, and supporting-file metadata
- Updated BOM and C/O stores to prefer Postgres and keep filesystem JSON only as offline fallback.
- Added source index auto-initialization for new clients so the first catalog/BCCT upload writes to Postgres.
- Added CLI commands:
  - `npm run db:import-app-state`
  - `npm run db:import-workflow-state`
- Committed the work in focused commits through `af9b7fb Initialize source indexes for new clients`.

## Decisions Made
- Raw uploaded files stay on filesystem/object storage. Postgres stores path/hash/size/MIME/original and stored filenames.
- No per-company tables. Company-specific data is separated by `client_id` rows in shared tables.
- Runtime behavior is dual-mode:
  - Postgres mode when `BARRY_DATABASE_URL` is set.
  - JSON/local fallback when Postgres is not configured.
- `PortfolioService` is the boundary for shared source/config interactions from C/O routes.
- Source indexes are initialized empty for new Postgres clients instead of requiring a manual rebuild before first upload.
- Existing C/O case persistence semantics were preserved: case metadata, shipment, and supporting files persist; full evaluated origin edits are not newly persisted yet.

## What Didn't Work
- Leaving source write activation dependent on pre-existing source indexes caused a gap for brand-new clients. Fixed by auto-initializing empty source indexes.
- A temporary DB cleanup smoke initially tried to delete from `clients` by `client_id`; the table uses `id`. The cleanup was rerun correctly and the temporary client was removed.
- Attempting to spawn another explorer near the end hit the agent thread limit, so the new-client source-index change was inspected directly.

## Open Items
- Decide whether production should hard-require Postgres and disable JSON fallback outside offline/local dev.
- Persist full evaluated C/O product/origin payloads if refresh-safe origin editing is required.
- Move large source tables to SQL pagination/search instead of materializing full workspace rows.
- Define and document the BCQT consumer API contract before integrating `BCQT-System`.
