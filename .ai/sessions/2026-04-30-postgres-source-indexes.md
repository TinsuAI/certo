# Session: Postgres Source Indexes

## What Was Done
- Created branch `sprint/postgres-source-indexes-20260430`.
- Measured the Growatt C/O performance problem:
  - C/O case JSON was only a few KB and loaded in about `0.1 ms`.
  - Growatt `bcct/state.json` was about 92 MB with `19,901` rows.
  - `get_source_workspace()` took about `1.2-1.4s` and was being called twice per C/O request.
  - C/O pages were around `2.7-3.0s` before optimization.
- Added discovery brief `.ai/features/2026-04-30-postgres-source-indexes.md`.
- Added a PostgreSQL read-model/index layer:
  - `db/migrations/001_source_indexes.sql`
  - `app/source_index_store.py`
  - `app/source_index_cli.py`
- Added npm scripts for the index workflow:
  - `npm run db:migrate`
  - `npm run db:rebuild-source-index -- <client_id>`
- Added `psycopg[binary]` to Python dependencies.
- Updated C/O context loading:
  - stopped loading the full source workspace twice on C/O pages
  - added source summary helpers for file fallback
  - used Postgres for source summary and invoice matching when indexes exist
  - preserved JSON source files as source of truth/fallback
- Added tests for:
  - C/O pages not calling full source workspace
  - source summary counts/snapshot metadata
  - Postgres invoice-token index records
  - C/O pages using the Postgres source index when available
- Installed PostgreSQL 16 in the current WSL environment.
- Created local app database and rebuilt Growatt indexes:
  - `19,901` BCCT rows
  - `20,049` invoice tokens
  - `19,370` C/O stock rows
- Restarted the visible tmux dev server with `BARRY_DATABASE_URL` set so browser testing uses the Postgres index.
- Committed implementation as `463ff8c Add Postgres source indexes`.

## Decisions Made
- Use Postgres as a read model/index first, not as the source of truth for all source uploads.
- Keep JSON source files authoritative during this phase to avoid a risky full data migration.
- Use `BARRY_DATABASE_URL` as the app-specific database connection setting.
- Use plain SQL migrations under `db/migrations/` instead of introducing Alembic before the schema stabilizes.
- Promote hot lookup/filter fields to columns and preserve full BCCT/stock payloads in `jsonb`.
- Use an invoice-token table so invoice matching avoids scanning all BCCT rows.
- Keep catalog and BCCT table screens on the file-backed source workspace for now; SQL pagination is a separate pass.

## What Didn't Work
- Docker was not available in this WSL distro because Docker Desktop WSL integration was not enabled, so a Dockerized Postgres path could not be used.
- `psql` was initially missing. Installing PostgreSQL directly in WSL resolved this.
- The first tmux restart attempt reused a stale prompt/partial command and failed. Clearing the prompt and restarting the command cleanly fixed it.
- Running with `uvicorn --reload` still causes slow first requests after file-change reloads. Warm Postgres-indexed requests are fast.

## Open Items
- Manual browser validation is still needed against the current Postgres-backed tmux server.
- Decide whether BCCT table/catalog screens should move to SQL pagination.
- Decide whether C/O dossier JSON storage should move to Postgres.
- Resolve or rebaseline the existing Node legal lookup `raw-binary` failures.
- Define structured HS/PSR legal rule lookup before showing final origin pass/fail.
