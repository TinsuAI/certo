# Session: Portfolio Postgres Boundary

## What Was Done
- Researched the current C/O and BCQT split and documented a shared company/source portfolio direction in `.ai/features/2026-04-30-shared-company-portfolio-for-bcqt-and-co.md`.
- Documented the immediate Postgres source workspace slice in `.ai/features/2026-04-30-postgres-portfolio-source-workspace.md`.
- Extended the existing Postgres source index schema:
  - added `source_catalog_rows` for material/product catalog current rows,
  - added `source_correction_candidates` for review candidates,
  - retained `bcct_rows`, `bcct_invoice_index`, `co_stock_rows`, and `source_index_metadata`.
- Extended `app/source_index_store.py`:
  - `build_catalog_index_records()`
  - `build_correction_candidate_records()`
  - catalog row reads,
  - BCCT row reads,
  - correction candidate reads,
  - `source_workspace()` returning the same shape templates already expect,
  - complete client rebuild from JSON fallback state into Postgres read models.
- Updated `app/source_store.py` with `enrich_client_with_source_workspace()` so the C/O app can enrich client counts from either file or portfolio/Postgres workspaces.
- Updated `app/main.py` initially to prefer Postgres source workspace for source table pages, then extracted the shared source/config calls behind a portfolio adapter.
- Added `app/portfolio.py`, a mounted FastAPI app at `/portfolio`, with:
  - dashboard UI,
  - `/portfolio/api/clients`,
  - `/portfolio/api/clients/{client_id}`,
  - `/portfolio/api/clients/{client_id}/source-summary`,
  - `/portfolio/api/clients/{client_id}/source-workspace`,
  - `/portfolio/api/clients/{client_id}/config` GET/PUT,
  - `PortfolioService` adapter used by C/O.
- Added `app/templates/portfolio.html` and a top-nav link to `/portfolio`.
- Updated tests in `tests/test_co_demo.py`:
  - TDD red tests first for catalog index records and Postgres-backed source table pages.
  - Portfolio dashboard/API smoke coverage.
  - C/O routes using `portfolio_service` fake, proving the adapter boundary.
  - Existing Postgres tests now monkeypatch `app.portfolio` instead of `app.main`.
- Applied/migrated local Postgres `barry_co` and rebuilt indexes for Growatt, Johnson, and Do Thanh.
- Verified local DB state:
  - Growatt: 241 material rows, 34 product rows, 19,901 reviewed BCCT rows, 19,370 C/O stock rows.
  - Johnson: 3 material rows, 2 product rows, no BCCT/C/O stock.
  - Do Thanh: metadata rows only, no source rows.
- Verification:
  - `uv run pytest -q` -> `83 passed`.
  - `uv run python -m py_compile app/main.py app/portfolio.py` passed.
  - Playwright desktop/mobile browser smoke tests passed for portfolio dashboard/API and C/O catalog/BCCT pages.

## Decisions Made
- Treat “tách app” as a first bounded FastAPI app/module inside the same repo/process before creating a separate deployment. This keeps the demo stable while establishing the contract boundary.
- C/O should consume shared source evidence through `portfolio_service`; it should not directly reach into `source_store`, `source_index_store`, or `client_config_store` for shared source surfaces.
- Postgres currently stores shared source read models/indexes, not every source-of-truth record.
- Raw uploaded files should not move into Postgres. Keep binaries on filesystem/object storage and store path/hash/metadata in Postgres when source-of-truth migration happens.
- The next migration should move source metadata/state to Postgres in slices rather than rewriting all app state at once:
  1. client config,
  2. source upload metadata/snapshots/versions/diffs/audit,
  3. BOM metadata/current rows,
  4. C/O case workflow state only if needed, and not as part of the shared portfolio boundary.
- BCQT should integrate later through a portfolio adapter/API contract. Do not merge BCQT and C/O apps directly.

## What Didn't Work
- A Puppeteer UI smoke attempt failed because `node_modules` is not installed in this repo, despite `puppeteer` being listed in `package.json`.
- Playwright via `uv run --with playwright` worked and was used for browser testing instead.
- One initial mobile BCCT assertion used a DB row that was not visible on the first sorted page; the test was corrected to search by query string before asserting the row appears.
- After extracting the adapter, old tests that monkeypatched `app.main.get_source_index_store` failed because `main` no longer owns that dependency. Tests were updated to patch `app.portfolio`, matching the new boundary.
- `python` is not available as a direct shell command in this environment; use `uv run python`.

## Open Items
- Commit the current work.
- Decide whether to make `app/portfolio.py` the source-of-truth writer next or keep it as a facade while migrating tables behind it.
- Design and implement Postgres tables for source upload metadata, parsed snapshots, published versions, diffs, and audit events.
- Move client config to Postgres if the user wants more of the portfolio state centralized next.
- Add SQL-level pagination/search for large BCCT/catalog views before portfolio API usage grows.
- Define BCQT adapter contract for clients/catalogs/BCCT/BOM snapshots before modifying the sibling `BCQT-System` repo.
- Confirm whether `/portfolio` should remain mounted in the C/O process for now or become a separately served app with its own port/auth later.
