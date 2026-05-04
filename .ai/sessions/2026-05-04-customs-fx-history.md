# Session: Customs FX History and Data Hub Contract

## What Was Done
- Refreshed project context and kept the local CO dev server running at `http://127.0.0.1:8001`.
- Investigated why `/customs-exchange-rates/refresh` failed when `DATA_HUB_ENABLED=1`.
- Confirmed the failure was a CO guardrail, not a network error:
  - `require_local_source_writes()` blocked shared-source writes while Data Hub mode is active.
  - customs FX is not currently available from Data Hub, so blocking the temporary CO refresh was premature.
- Implemented the temporary CO fix:
  - removed the local-source write guard from `/customs-exchange-rates/refresh`.
  - kept BCCT/BOM/catalog/config write guards unchanged.
  - changed UI copy to identify customs FX as temporarily stored in CO until Data Hub has a contract.
- Created `.ai/api-requests/2026-05-04-customs-exchange-rates.md` for Data Hub ownership of customs exchange rates.
- Investigated the official Customs exchange-rate page at `https://www.customs.gov.vn/index.jsp?pageId=18&cid=116`.
- Found that the page loads module `/modules/tracuutygia/index.jsp`.
- Confirmed that:
  - `GetListUSDRate` returns USD history.
  - `GetListOtherRate` returns only current-list rows for non-USD currencies.
  - historical lookup uses `POST /customs/api/GetListRateByNameOrDate`.
- Updated `app/customs_fx_store.py` to refresh through `GetListRateByNameOrDate`, defaulting from January 1 two years ago through today.
- Refreshed the local customs FX store:
  - CLI refresh returned `fetched=3610 saved=3610 currencies=30 latest=2026-05-04`.
  - UI refresh on `localhost:8001` returned `200 OK` and reported `3610` rows.
  - USD/JPY/EUR each now have `123` local historical rows from `2024-01-01` through `2026-05-04`.
- Updated tests for the temporary Data Hub-mode exception and historical FX parsing/fetch behavior.
- Verification completed:
  - targeted customs/Data Hub policy tests passed.
  - full `uv run pytest` passed `163 passed`.
  - local `/healthz` returned OK.

## Decisions Made
- Keep customs FX temporarily local in CO because Data Hub has no approved endpoint yet, but document the Data Hub contract request immediately.
- Treat customs exchange rates as global reference data that should move to Data Hub after contract approval.
- Use `GetListRateByNameOrDate` as the canonical upstream fetch path for CO/Data Hub customs FX history, not `GetListOtherRate`.
- Fetch all currencies in one historical query with empty `ten_ngoai_te`; this matched the official page API and avoided per-currency loops.
- Default historical refresh range to January 1 two years before the current year through today. This gives useful history for active dossiers without creating a very large local pull.
- Do not add new `/v1/hub/*` literals to `app/data_hub_client.py` until the Data Hub-side contract and provider tests are approved.

## What Didn't Work
- Initial assumption that `GetListOtherRate` was the relevant endpoint for non-USD history was wrong; it only returned current-list rows.
- Adding date-like query parameters to `GetListOtherRate` (`date`, `fromDate/toDate`, `ngay`) returned the same current-list payload.
- The static page HTML did not expose the FX logic directly because the site loads modules dynamically. Fetching `/modules/tracuutygia/index.jsp` exposed the real endpoint.
- Sending `Content-Type: application/json` to the Customs bridge produced a 400 in some probes. Posting the JSON string the same way the page's jQuery code does worked.

## Open Items
- Review and approve `.ai/api-requests/2026-05-04-customs-exchange-rates.md` with the Data Hub contract owner.
- Implement the Data Hub customs FX endpoints/provider tests in the Data Hub repo.
- After Data Hub implementation, update CO to read customs FX through `app/data_hub_client.py` and remove the CO-local refresh exception in Data Hub mode.
- Decide whether the two-year default history range is enough for production or whether Data Hub should backfill a larger range.
- Keep unrelated pre-existing worktree artifacts separate unless the user explicitly asks to include them.
