# Project Status

## Current State
- Active branch: `sprint/postgres-source-indexes-20260430`.
- Working tree was clean before this handoff update.
- The app is still a FastAPI/Jinja C/O app with a mounted portfolio boundary at `/portfolio`.
- Postgres is the primary runtime state store when `BARRY_DATABASE_URL` is set. Filesystem JSON remains an offline fallback only when Postgres is unavailable.
- Raw uploaded binaries are intentionally still stored on filesystem/object storage. Postgres stores metadata/path/hash/size/MIME plus parsed rows, versions, and workflow state.
- `app/portfolio.py` is the shared portfolio/source boundary. C/O routes use `portfolio_service` for shared source/config operations.
- New Postgres clients now get empty source indexes automatically, so their first catalog/BCCT upload writes to Postgres instead of JSON fallback.
- Local `barry_co` has migrations 1-5 applied. Current checked counts:
  - `clients=3`, `client_configs=3`
  - `source_index_metadata=12`, `source_module_state=9`
  - `source_uploads=4`, `source_catalog_rows=281`, `bcct_rows=19901`, `bcct_invoice_index=20049`, `co_stock_rows=19370`
  - `source_snapshot_rows=20169`, `source_version_rows=20190`
  - `bom_states=3`, `bom_uploads=1`, `bom_versions=4`, `bom_version_rows=11`
  - `co_case_states=3`, `co_cases=2`, `co_supporting_files=1`

## Recent Changes
- Added Postgres portfolio boundary and app-state stores.
- Added migrations:
  - `001_source_indexes.sql`: source read models.
  - `002_application_core.sql`: clients and client configs.
  - `003_source_upload_metadata.sql`: source uploads/raw files/snapshots/versions/audit.
  - `004_source_history_rows.sql`: source snapshot/version rows.
  - `005_workflow_state.sql`: BOM and C/O workflow state tables.
- Source catalog/BCCT upload writes now go through Postgres for indexed clients; parsed snapshot rows and historical version rows are persisted.
- BOM state, uploads, snapshots, product versions, aggregate versions, rows, and audit now use Postgres when configured.
- C/O case state and supporting-file metadata now use Postgres when configured.
- New clients are auto-initialized with empty source indexes via `PostgresAppStateStore.upsert_client()` and `PostgresSourceIndexStore.has_client()`.
- Latest relevant commits:
  - `80e19c0 Add Postgres portfolio boundary`
  - `fa632bd Move clients and config to Postgres`
  - `69f755f Standardize source upload metadata`
  - `845db8c Write source uploads through Postgres`
  - `de5f8c9 Persist source history rows in Postgres`
  - `c4c25d5 Move workflow state to Postgres`
  - `af9b7fb Initialize source indexes for new clients`

## Verification
- `uv run pytest -q` -> `92 passed`.
- Pycompile checks passed for the changed Postgres/source/workflow modules.
- Local Postgres smokes passed:
  - migrated/imported app state and workflow state into `barry_co`
  - rebuilt source indexes for Growatt, Johnson, and Do Thanh
  - direct source upload writes persisted to Postgres
  - BOM upload and C/O supporting-file metadata persisted to Postgres
  - temporary new client initialized empty source indexes and wrote first catalog upload through Postgres

## Next Steps
1. Decide whether deployment should hard-require `BARRY_DATABASE_URL` and disable JSON fallback outside local/offline dev.
2. Persist full evaluated C/O product/origin payloads if users need edited origin calculations to survive refresh; current behavior preserves the existing app contract of persisting case metadata, shipment, and supporting files.
3. Add SQL pagination/search for large source views. Current table pages can still materialize workspace rows before table filtering.
4. Define the BCQT consumer adapter contract against portfolio APIs before touching `BCQT-System`.

## Blockers
- Portfolio is a bounded app boundary mounted in the same FastAPI process, not a separately deployed service yet.
- Existing Node legal lookup test failures from prior sessions were not rerun; they are unrelated to the Postgres migration work.

## Notes for Next AI Session
- User prefers Vietnamese replies when writing Vietnamese. Project docs and handoff artifacts should stay in English unless client-facing.
- Do not move raw file bytes into Postgres unless explicitly requested. The agreed design is filesystem/object storage for binaries plus DB metadata/path/hash.
- Keep source/portfolio access behind `portfolio_service`; do not reintroduce direct source-store calls in `app/main.py`.
- Keep `data/` and `temp/` runtime artifacts uncommitted.
