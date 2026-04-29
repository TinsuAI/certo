# Project Status

## Current State
- Active branch: `sprint/postgres-source-indexes-20260430`.
- Latest implementation commit: `463ff8c Add Postgres source indexes`.
- The FastAPI/Jinja C/O demo still treats C/O as the primary shipment workflow:
  - `/clients/{client_id}/co-case` creates/opens dossiers.
  - `/clients/{client_id}/co-case/{case_id}` opens the shipment step.
  - `/clients/{client_id}/co-case/{case_id}/{step}` supports `shipment`, `documents`, `exports`, `guidance`, `origin`, and `review`.
- A PostgreSQL read-model/index layer now exists for source data:
  - `bcct_rows`
  - `bcct_invoice_index`
  - `co_stock_rows`
  - `source_index_metadata`
- JSON source files remain the source of truth/fallback. Postgres is currently a fast read model for C/O source summary, invoice matching, and derived C/O stock indexes.
- Local PostgreSQL 16 is installed in the current WSL environment and the Growatt index has been rebuilt in the local app database.
- The visible tmux dev server is running in `1-CO-MAIN:barry-co-dev` with `BARRY_DATABASE_URL` set, so Growatt C/O pages use the Postgres index.
- The app still does not infer final HS-specific PSR criteria. Form rows correctly remain in `needs_rule_lookup` until a legal rule engine exists.

## Recent Changes
- Added discovery brief `.ai/features/2026-04-30-postgres-source-indexes.md`.
- Added Postgres migration `db/migrations/001_source_indexes.sql`.
- Added `app/source_index_store.py` for:
  - schema application
  - Growatt/client source index rebuild from existing JSON source state
  - indexed invoice matching
  - source summary lookup
  - C/O stock row lookup
- Added CLI `app/source_index_cli.py` and scripts:
  - `npm run db:migrate`
  - `npm run db:rebuild-source-index -- <client_id>`
- Added `psycopg[binary]` Python dependency.
- Updated C/O context loading to avoid full duplicate `get_source_workspace()` calls on C/O pages.
- C/O pages now use Postgres indexes when available and fall back to JSON source files when `BARRY_DATABASE_URL` is unset or a client has no index.
- Added docs at `docs/postgres-source-indexes.md`.
- Expanded Python regression coverage for lightweight C/O source summary and Postgres-indexed C/O matching.

## Next Steps
1. Run the Growatt manual browser test against the current tmux server and confirm uploads, reject cases, export workbook, and perceived speed.
2. Decide whether to move BCCT table/catalog screens to SQL pagination. They still use file-backed source workspace in this phase.
3. Decide when C/O dossiers themselves should move from JSON files to Postgres.
4. Resolve or intentionally rebaseline the 3 known Node legal lookup failures so project-level `npm test` is trustworthy.
5. Define the structured PSR/HS legal rule lookup model before replacing `needs_rule_lookup` with final origin qualification.

## Blockers
- `npm test` still fails 3 known legal lookup `raw-binary` source-link expectations in `tests/legal-lookup-server.test.mjs`; this predates and is unrelated to the Postgres source-index work.

## Notes for Next AI Session
- Python verification: `uv run pytest tests/test_co_demo.py -q` passed with `79 passed`.
- `uv run python -m compileall app` passed.
- `git diff --check` passed after the handoff artifact edits.
- `npm test` still reports 53 passing and 3 failing legal lookup tests with missing `raw-binary` source links.
- Postgres import verification for Growatt: `19,901` BCCT rows, `20,049` invoice tokens, and `19,370` C/O stock rows.
- C/O context timing with Postgres index was roughly `13-28 ms` after warm-up; live `/exports` curl was about `24-27 ms` after warm-up.
- Keep source files and manual test files ignored; do not commit runtime `data/` or `temp/` artifacts.
- User prefers Vietnamese replies when writing Vietnamese; project docs and handoff artifacts stay in English unless client-facing.
