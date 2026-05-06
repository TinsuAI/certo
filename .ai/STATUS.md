# Project Status

## Current State
- Active branch: `main`; do not push unless the user asks.
- Local CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returned `{"status":"ok"}` on 2026-05-06.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- C/O origin allocation remains snapshot-only inside CO, but calculation/export now uses a customer-scoped soft lock:
  - multiple dossiers for the same customer can be opened and prepared in parallel
  - only one dossier per customer can hold the origin stock calculation session at a time
  - `Tính lại snapshot` and dossier XLSX export acquire/renew the lock
  - other dossiers stay editable for preparation but cannot calculate/export official origin stock output until the lock is released
  - lock TTL is currently 60 minutes
- The C/O case overview now shows stock lock state prominently:
  - a `Phiên tính tồn đang mở` banner shows the dossier holding the lock
  - the banner has `Mở hồ sơ giữ tồn` and `Nhả phiên`
  - the dossier table has a `Tồn C/O` column with `Đang giữ tồn`, `Chỉ chuẩn bị`, or `Sẵn sàng`
- Dossier deletion is implemented with backend guardrails:
  - only roles configured in Technical Settings `CO_CASE_DELETE_ROLES` can delete
  - draft/preparation dossiers can be deleted
  - dossiers holding the stock lock must release it before deletion
  - completed/submitted/closed dossiers cannot be deleted
  - delete uses an in-app confirmation modal, not browser `confirm()`
- The C/O case overview no longer uses a sidebar for `Tạo hoặc mở hồ sơ`; the create form is in the main view above the full-width dossier list.
- Pre-existing unrelated worktree artifacts remain separate and should not be committed unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
- Local screenshot artifacts remain under `.ai/screenshots/`; they are not required for the current commit.

## Recent Changes
- Added customer-scoped origin calculation lock persistence in `app/co_case_store.py`.
- Added lock acquisition/enforcement for origin recalculation and case workbook export in `app/main.py`.
- Added release route support with `next_url`, so locks can be released directly from the overview.
- Added delete route and store deletion with upload cleanup, permission checks, lock checks, and completed-case checks.
- Added configurable delete roles through Data Hub/Technical Settings as `CO_CASE_DELETE_ROLES`.
- Reworked `app/templates/co_case.html` and `app/static/css/app.css`:
  - overview lock banner
  - `Tồn C/O` status column
  - release lock action from overview
  - delete action and confirmation modal
  - full-width overview list with create form in main content
  - mobile fixes for overview list and create form
- Added/updated regression coverage in:
  - `tests/test_co_demo.py`
  - `tests/test_data_hub_integration.py`
- Verification completed:
  - `uv run pytest` passed: `173 passed in 31.66s`
  - targeted overview/delete tests passed
  - `curl -fsS http://127.0.0.1:8001/healthz` returned `{"status":"ok"}`

## Next Steps
1. Manually review the C/O case overview in a real authenticated Data Hub session, especially lock release, delete modal, and mobile layout.
2. Confirm the production definition of a “completed” dossier. Current delete blocking recognizes `completed`, `done`, `finished`, `submitted`, and `closed` from `status`, `case_status`, or `origin_snapshot.case_status`.
3. Decide whether the origin calculation lock should move from CO local state into a Data Hub-owned reservation/ledger when global shared stock decrement becomes real.
4. Revisit mixed-currency allocation rules before automatically summing VNM across currencies.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: briefly say what was inspected, what failed, and how it was resolved.
- The term to use in Vietnamese UI is “dòng tồn”, not “lot”.
- Current allocation behavior is still snapshot-only inside CO. The new lock prevents concurrent same-customer calculations in CO, but it does not reserve/decrement shared stock globally.
- Do not commit unrelated `docs/co-form-index-confirmation.*` changes unless the user explicitly asks.
- Screenshot folders under `.ai/screenshots/` are local verification artifacts; keep them out of commits unless explicitly requested.
