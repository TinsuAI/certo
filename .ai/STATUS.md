# Project Status

## Current State
- Active branch: `main`.
- After the customs FX commit, `main` is expected to be ahead of `origin/main` by 25 commits. Nothing has been pushed.
- CO dev server is running at `http://127.0.0.1:8001`.
- A sibling Data Hub dev server is running at `http://127.0.0.1:8754`.
- Local runtime config still has `CO_AUTH_REQUIRED=1` and `DATA_HUB_ENABLED=0` in `data/local/runtime/data-hub-link.json`; Data Hub SSO is active, but Data Hub-backed source/master data mode is off.
- Customs exchange rates are now implemented as app-level shared reference data, not client-owned data:
  - app-level route: `/customs-exchange-rates`
  - old client route `/clients/{client_id}/customs-exchange-rates` redirects to the app-level page
  - storage scope is `client_id='global'`
  - JSON fallback path is under ignored `data/local/customs-fx/`
  - Postgres table is `customs_exchange_rate_rows`
- Pre-existing uncommitted BOM/Data Hub discovery artifacts remain outside the customs FX commit unless the user asks to commit them separately:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`
- CO still stores BOM state locally/Postgres today. `app/data_hub_client.py` has no BOM API methods yet, and CO does not consume Data Hub BOM.
- Data Hub has BOM schema/API/data, but it does not yet implement the full technical-to-flat BOM engine needed before CO should migrate BOM ownership.

## Recent Changes
- Explored sibling `barry-CO*` repos for prior customs FX work.
- Found the old `barry-CO/scripts/download-customs-fx-rates.py` public customs API downloader and Growatt valuation notes showing why source `exchange_rate` cannot be trusted as USD rate by default.
- Added customs FX implementation in CO:
  - `app/customs_fx_store.py`
  - `app/customs_fx_cli.py`
  - `db/migrations/006_customs_exchange_rates.sql`
  - app-level Jinja page `app/templates/customs_exchange_rates.html`
  - topnav link “Tỷ giá HQ”
  - npm script `customs-fx:refresh`
- Added tests for:
  - Vietnamese rate parsing (`26.130 VNĐ` -> `26130`)
  - public customs JSON endpoint fetch with `httpx.MockTransport`
  - JSON fallback upsert behavior
  - app-level route refresh/filter behavior
  - client route redirect to app-level route
- Ran a live customs FX refresh. It fetched 70 rows, 30 currencies, latest effective date `2026-04-30`, and stored them in JSON fallback because the shell had no `BARRY_DATABASE_URL`.

## Verification
- `uv run pytest tests/test_co_demo.py -q` passed: 97 tests.
- `uv run pytest -q` passed: 135 tests.
- `npm run customs-fx:refresh` succeeded against live customs endpoints: 70 rows, 30 currencies, latest `2026-04-30`.
- `curl http://127.0.0.1:8001/customs-exchange-rates` returned `200 OK`.
- `git diff --check` passed.
- Existing known issue remains: `npm test` previously failed 3 unrelated legal lookup tests expecting `raw-binary` source links; this session did not rerun Node tests.

## Next Steps
1. Commit/push policy: push only when the user explicitly asks.
2. Decide whether customs FX should eventually become Data Hub-owned shared master/reference data. If yes, create a Data Hub API request artifact first and do not add raw Data Hub calls outside `app/data_hub_client.py`.
3. Later wire customs FX lookup into valuation/origin calculation where import-side VND tax price needs USD normalization; snapshot the selected FX version/rate into each case when used.
4. In the Data Hub repo, implement the technical BOM flattener before migrating CO BOM ownership.
5. Triage the existing Node legal lookup `raw-binary` failures if a fully green Node suite is required.

## Blockers
- CO BOM migration remains blocked until Data Hub implements technical BOM flattening and exposes enough structured version metadata for consumers.
- Customs FX integration into actual valuation is intentionally not done yet; current work only fetches, stores, and displays the app-level rate table.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese when the user writes Vietnamese. Project docs and handoff artifacts remain English unless client-facing.
- The app-level customs FX route is `/customs-exchange-rates`; avoid moving it back into client-owned navigation.
- Keep customs FX DB/API machine fields in English and UI labels in Vietnamese.
- Current CO dev server session was started with `npm run co:serve`; if port `8001` is closed next session, restart it.
