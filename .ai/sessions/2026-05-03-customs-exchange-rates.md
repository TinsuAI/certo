# Session: Customs Exchange Rates

## What Was Done
- Refreshed project context from `.ai/STATUS.md`, `.ai/DECISIONS.md`, recent session summaries, and `AGENTS.md`.
- Started the CO dev server on `http://127.0.0.1:8001`; Data Hub was already running on `http://127.0.0.1:8754`.
- Explored sibling `barry-CO*` repos for prior customs FX work:
  - old `barry-CO/scripts/download-customs-fx-rates.py` fetched `GetListDongTienTyGia`, `GetListUSDRate`, and `GetListOtherRate` from `customs.gov.vn`
  - old Growatt valuation code used customs USD rate by declaration date before falling back to source exchange rate
  - old docs warned not to treat source `exchange_rate` as a reliable USD conversion basis
- Added app-level customs exchange rate support:
  - `app/customs_fx_store.py` fetches/parses public customs JSON, stores rows, and supports JSON fallback/Postgres.
  - `app/customs_fx_cli.py` exposes a CLI refresh command.
  - `db/migrations/006_customs_exchange_rates.sql` adds `customs_exchange_rate_rows` and `customs_exchange_rate_refreshes`.
  - `package.json` adds `npm run customs-fx:refresh`.
  - `app/main.py` adds app-level routes `/customs-exchange-rates` and `/customs-exchange-rates/refresh`.
  - `app/templates/customs_exchange_rates.html` renders the table with filters/search/pagination.
  - `app/templates/base.html` adds the topnav “Tỷ giá HQ” link.
  - Client workspace now links to `/customs-exchange-rates`; the old client route redirects to the app-level page.
- Added tests in `tests/test_co_demo.py` for parser correctness, mocked endpoint fetches, file-store upserts, route refresh/filter behavior, and client-route redirect.
- Ran live customs refresh through the new CLI. It fetched 70 rows across 30 currencies with latest effective date `2026-04-30`.

## Decisions Made
- Customs exchange rates are app-level shared reference data, not client-level data.
- Store the canonical local table under `client_id='global'` to reuse the existing app patterns while keeping ownership clear.
- The primary UI route is `/customs-exchange-rates`; client-specific URL is only a redirect.
- Keep old customs rows when refreshing, because the public endpoint may return only a recent window.
- Do not add a Data Hub customs FX endpoint or raw Data Hub calls from CO. If Data Hub should own this later, request and approve that contract first.
- This pass only fetches/stores/displays FX rates; actual valuation normalization should be wired separately with case-level snapshots.

## What Didn't Work
- The first implementation exposed the page under `/clients/{client_id}/customs-exchange-rates`, which made ownership look client-level. The user caught this; the surface was moved to app-level.
- Moving the page out of `_client_nav.html` removed the shared toast area, causing a route test to fail. Adding local toast rendering in the app-level template fixed it.
- CO dev server was found stopped after verification; it was restarted and `/customs-exchange-rates` returned `200 OK`.

## Open Items
- Decide whether customs FX should eventually be owned by Data Hub as shared reference/master data.
- Wire customs FX lookup into valuation/origin calculation where import-side VND tax price is normalized to USD.
- Snapshot the selected exchange rate/version into C/O cases once rates affect calculations.
- Commit or discard the pre-existing uncommitted BOM/Data Hub discovery artifacts separately.
- Existing Node legal lookup `raw-binary` test failures remain unrelated and unresolved.
