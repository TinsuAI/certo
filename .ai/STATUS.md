# Project Status

## Current State
- Active branch: `main`; latest local work is a focused customs exchange-rate fix and handoff commit, not pushed unless the user asks.
- Local CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returns `{"status":"ok"}`. With auth enabled, unauthenticated app pages redirect to `/auth/login`.
- CO demo deploy remains Docker Compose based on app port `8755`; CO CI/CD exists in `.github/workflows/ci.yml`.
- Data Hub CI/CD already exists per user correction. Do not keep recommending Data Hub CI/CD setup as a next step.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- Customs exchange rates are still temporarily stored/refreshed in CO because Data Hub does not yet own a customs FX contract.
- CO customs FX refresh now uses the same historical lookup endpoint as the official Customs page, `POST /customs/api/GetListRateByNameOrDate`, instead of only current-list endpoints.
- Pre-existing unrelated worktree artifacts remain separate and should not be committed unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`
  - `.ai/sessions/2026-05-04-origin-web-snapshot.md`

## Recent Changes
- Fixed the CO customs exchange-rate refresh path while `DATA_HUB_ENABLED=1`:
  - `/customs-exchange-rates/refresh` is no longer blocked by the shared source write guardrail.
  - Shared-source writes for BCCT/BOM/catalog/config remain blocked in Data Hub mode.
  - UI copy now says the customs FX table is temporarily stored in CO until Data Hub has a contract.
- Investigated the official Customs FX page at `https://www.customs.gov.vn/index.jsp?pageId=18&cid=116`.
  - The page module `tracuutygia` loads current lists with `GetListUSDRate` and `GetListOtherRate`.
  - Historical search uses `POST /customs/api/GetListRateByNameOrDate`.
  - The API accepts `ten_ngoai_te`, `hieu_luc_tu_ngay`, `hieu_luc_den_ngay`, `language`, and `captcha`; an empty currency fetches all currencies in the date range.
- Updated `app/customs_fx_store.py` so refresh pulls historical rows through `GetListRateByNameOrDate`, defaulting from January 1 two years ago through today.
- Refreshed local customs FX data:
  - UI refresh reported `3610` rows, `30` currencies, latest `2026-05-04`.
  - USD/JPY/EUR each have `123` local rows from `2024-01-01` through `2026-05-04`.
- Added Data Hub API request artifact:
  - `.ai/api-requests/2026-05-04-customs-exchange-rates.md`
  - Requests list/latest/refresh endpoints and provider tests for Data Hub-owned customs FX.
- Added/updated regression tests for:
  - customs FX refresh allowed in Data Hub mode until the Hub contract exists.
  - source write guardrails still blocking BCCT/BOM writes.
  - historical customs FX endpoint usage and multi-row non-USD history.

## Next Steps
1. Review and approve the Data Hub customs FX contract request, then implement provider-side endpoints/tests in Data Hub.
2. After Data Hub owns customs FX, update CO to consume rates only through `app/data_hub_client.py` in Data Hub mode and retire the CO-local refresh exception.
3. Consider branch protection for CO and Data Hub `main` branches now that both repos have CI/CD.
4. Continue the business-priority CO work: exact legacy-style Excel `bảng kê` export from the accepted web `Xuất xứ` snapshot.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: say what was inspected, what failed, and what resolved it.
- The important customs FX finding: `GetListOtherRate` only returns a current list; full history comes from `GetListRateByNameOrDate`.
- The official Customs page requires captcha in UI, but the underlying JSON endpoint returned historical rows with an empty captcha in local testing.
- Keep Data Hub endpoint additions behind the API request/approval process. `tests/test_data_hub_policy.py` will fail on unapproved raw `/v1/hub/*` literals.
- For server operations in this environment, follow the Windows OpenSSH workaround from prior session instructions instead of WSL native SSH.
- GitHub Actions currently shows Node.js 20 deprecation annotations for standard actions. These are warnings only and did not fail the workflow.
