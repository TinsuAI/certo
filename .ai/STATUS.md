# Project Status

## Current State
- Active branch: `sprint/postgres-source-indexes-20260430`.
- Latest committed checkpoint: `80e19c0 Add Postgres portfolio boundary`.
- Current uncommitted changes implement the first full-Postgres migration slice: shared migration tracking plus Postgres-backed clients and client configs.
- The C/O app still runs as the main FastAPI/Jinja app, but it now mounts a separate portfolio app at `/portfolio`.
- `app/portfolio.py` is the new source/portfolio boundary. It exposes:
  - UI dashboard at `/portfolio`
  - JSON APIs under `/portfolio/api/clients...`
  - `PortfolioService` adapter methods used by C/O for source workspace, C/O source context, source uploads/templates, client config, and index refresh.
- `app/main.py` no longer directly calls source index/source JSON/client config stores for the shared source surfaces. It calls `portfolio_service` instead.
- `app/client_registry.py` now lets the app read clients from Postgres when imported, with seed fallback while the migration is staged.
- PostgreSQL local database `barry_co` currently contains source read models:
  - `schema_migrations`: 2 rows
  - `clients`: 3 rows
  - `client_configs`: 3 rows
  - `source_index_metadata`: 12 rows
  - `source_catalog_rows`: 280 rows
  - `bcct_rows`: 19,901 rows
  - `bcct_invoice_index`: 20,049 rows
  - `co_stock_rows`: 19,370 rows
  - `source_correction_candidates`: 0 rows
- Growatt is the main populated client in Postgres: 241 NVL rows, 34 SP rows, 19,901 reviewed BCCT rows, and 19,370 derived C/O stock rows.
- Postgres is now source-of-truth for imported client records and client config when `BARRY_DATABASE_URL` is set. JSON/filesystem state remains source of truth for source upload/version/audit history, BOM, C/O cases, and supporting files.
- The visible tmux dev server is still expected in `1-CO-MAIN:barry-co-dev` at `http://127.0.0.1:8001` with `BARRY_DATABASE_URL=postgresql:///barry_co`.

## Recent Changes
- Added discovery briefs:
  - `.ai/features/2026-04-30-shared-company-portfolio-for-bcqt-and-co.md`
  - `.ai/features/2026-04-30-postgres-portfolio-source-workspace.md`
  - `.ai/features/2026-04-30-full-postgres-migration.md`
- Extended Postgres schema in `db/migrations/001_source_indexes.sql` with:
  - `source_catalog_rows`
  - `source_correction_candidates`
- Added Postgres app-core schema in `db/migrations/002_application_core.sql` with:
  - `clients`
  - `client_configs`
- Added shared migration tracking via `schema_migrations`.
- Added `app/app_state_store.py`, `app/client_registry.py`, and `app/database.py`.
- Extended `app/source_index_store.py` to index and serve:
  - material/product catalog rows
  - BCCT rows
  - BCCT invoice index
  - C/O stock rows
  - correction candidates
  - full source workspace shape for templates
- Added `app/portfolio.py` and `app/templates/portfolio.html`.
- Added a top-nav link to `/portfolio`.
- Updated C/O routes to use `portfolio_service` for shared source/config interactions.
- Updated C/O routes to use `client_registry` for Postgres-backed client records when available.
- Updated `PortfolioService` to read/save client config through Postgres when `BARRY_DATABASE_URL` is configured.
- Updated CLI rebuild output to include catalog row count.
- Added CLI app-state import:
  - `npm run db:import-app-state`
- Added/updated regression tests for:
  - catalog index record builders
  - Postgres-backed source table workspace
  - portfolio dashboard/API
  - C/O routes using the portfolio service adapter
  - portfolio clients/config using Postgres app-state store
- Verification completed:
  - `uv run pytest -q` -> `85 passed`
  - `uv run python -m py_compile app/database.py app/app_state_store.py app/client_registry.py app/main.py app/portfolio.py app/source_index_store.py app/source_index_cli.py` passed
  - `BARRY_DATABASE_URL=postgresql:///barry_co uv run python -m app.source_index_cli migrate` passed
  - `BARRY_DATABASE_URL=postgresql:///barry_co uv run python -m app.source_index_cli import-app-state` imported 3 clients/configs
  - TestClient smoke with `BARRY_DATABASE_URL=postgresql:///barry_co` passed for `/portfolio/api/clients`, `/portfolio/api/clients/growatt/config`, and `/clients/growatt/config`
  - HTTP smoke against `http://127.0.0.1:8001` returned 200 for `/portfolio/api/clients` and `/clients/growatt/config`
  - Playwright desktop/mobile smoke tests passed for `/portfolio`, `/portfolio/api/clients/growatt/source-summary`, `/clients/growatt/catalog/materials?q=001.0001800`, and `/clients/growatt/bcct?q=307088602500`.

## Next Steps
1. Commit the current first Postgres source-of-truth slice for clients/client configs.
2. Start the next source-of-truth migration slice:
   - source upload metadata, parsed snapshots, published versions, diffs, and audit events in Postgres
   - keep raw uploaded files on filesystem/object storage with Postgres path/hash metadata
   - BOM metadata/current rows after source modules are stable
3. Add SQL pagination/search for large portfolio/catalog/BCCT views. Current table pages still materialize workspace rows before table filtering.
4. Define the BCQT consumer adapter contract against portfolio APIs before touching `BCQT-System`.
5. Decide whether C/O dossier workflow state should remain app-owned JSON for now or move to Postgres later as a separate non-portfolio migration.

## Blockers
- Portfolio is currently mounted in the same FastAPI process/repo. It is a bounded app boundary, not a separate deployed service yet.
- Postgres is not yet full source-of-truth for shared source evidence; JSON remains authoritative for source upload/version/audit history.
- Existing Node legal lookup test failures from prior sessions were not re-run in this handoff session and are unrelated to the portfolio/Postgres work.

## Notes for Next AI Session
- User prefers Vietnamese replies when writing Vietnamese. Project docs and handoff artifacts stay in English unless client-facing.
- The user clarified that raw files do not need to move into Postgres. Treat “move everything to Postgres” as metadata/state/parsed rows/version/audit records, while binary uploads stay as file/object storage referenced by path/hash.
- For source/portfolio work, do not reintroduce direct source-store calls in `app/main.py`. Use `portfolio_service` as the boundary.
- The project AGENTS instructions authorize subagents for codebase exploration; use them for future architecture/codebase research.
- Keep `data/` and `temp/` runtime artifacts uncommitted.
