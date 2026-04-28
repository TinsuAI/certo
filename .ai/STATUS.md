# Project Status

## Current State
- The repo has a working FastAPI/Jinja C/O demo app under `app/`, with client workspace views for overview, customs catalogs, BOM, C/O stock, BCCT, and C/O case.
- The latest working tree contains uncommitted changes for customs-standard source ingestion:
  - DS NVL DK HQ and DS SP DK HQ `.xls` parsing via `xlrd`.
  - BCCT `.xlsx` parsing with header row detection, including the HQ row-10 format.
  - ZIP upload support for source modules, selecting the matching workbook per module.
  - Source rows now preserve both normalized fields and original `raw_fields`/source metadata for audit.
- A discovery brief for splitting Catalog subviews and adding reusable advanced source tables exists at `.ai/features/2026-04-28-advanced-source-tables.md`.
- Runtime data remains local-only under `data/local/...`; current source sample files are under untracked `temp/`.

## Recent Changes
- Updated `app/source_store.py` to support real HQ schemas for:
  - `DANH MUC NPL DK HQ MOI.xls`
  - `DANH MUC SP DK HQ MOI.xls`
  - `BaoCaoHangChiTiet 01.01.2025 - 31.12.2025 08.01 or.xlsx`
- Added `xlrd>=2.0` to Python dependencies for `.xls` support.
- Updated Catalog and BCCT templates to accept `.xls/.xlsx/.zip` and expose more customs fields.
- Added regression tests for the real local HQ sample files; tests skip if the local ZIP is absent.
- Created extracted manual HQ files under `temp/manual-hq-files/` for browser testing.
- Reset local runtime source/BOM stores after schema changes, backing up previous local state to `data/local/setup-backups/20260428-231505-schema-change/`.
- Ran `/discover` for advanced tables and catalog subviews.

## Next Steps
1. Implement the advanced source table feature from `.ai/features/2026-04-28-advanced-source-tables.md`.
2. Split Catalog into DS NVL and DS SP child routes; remove the misleading visible `Mã nội bộ` column from DS NVL HQ UI.
3. Add a reusable server-side table helper/partial with search, filters, pagination, sorting, and summary/group chips.
4. Apply the table helper to DS NVL, DS SP, BCCT, and Tồn CO.
5. Add focused tests for route split, table query behavior, pagination boundaries, and upload result routing.
6. Manually re-test source uploads using the ZIP or files in `temp/manual-hq-files/`.

## Blockers
- `npm test` currently has 3 unrelated legal lookup failures around expected `raw-binary` source links. The CO demo pytest suite passes.
- Production database/auth/deploy decisions are still intentionally deferred.

## Notes for Next AI Session
- Start by reading `.ai/features/2026-04-28-advanced-source-tables.md`.
- Use `uv run pytest tests/test_co_demo.py -q` for the current CO app test suite; last run: `39 passed`.
- `npm test` is not clean due to pre-existing legal lookup expectations, not the C/O parser changes.
- Dev server was stopped during handoff. Start it with `npm run co:serve` or `uv run uvicorn app.main:app --host 127.0.0.1 --port 8001`.
- `data` in the repo is a symlink to a sibling local data directory.
- Do not commit `data/` runtime state or `temp/` sample uploads unless the user explicitly decides to version sanitized fixtures.
- User prefers Vietnamese replies when writing Vietnamese; docs/artifacts stay in English unless client-facing.
