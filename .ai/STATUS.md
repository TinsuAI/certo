# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; unauthenticated curl still redirects to `/auth/login`, so CO auth remains enabled.
- Sibling Data Hub dev server is running at `http://127.0.0.1:8754`; Data Hub read API was tested no-auth and now returns `200` for `/v1/hub/dncxs` and `/v1/hub/bcct/invoice-matches`.
- CO remains a Data Hub consumer in local runtime mode. Data Hub-owned catalog, BCCT, and BOM upload surfaces stay hidden/blocked in Data Hub mode; CO owns C/O case workflow files and generated outputs.
- C/O dossier flow has been polished:
  - new cases auto-generate a meaningful case code when the operator leaves `case_code` blank
  - workflow stepper now shows data-aware statuses instead of static labels
  - supporting files can be downloaded from the dossier document step
  - origin tab is read-first and keeps product/material values as hidden snapshot fields instead of exposing the old edit-heavy grid
  - legacy `Xuất evidence XLSX` action is removed from the C/O origin tab; dossier export remains
- `growatt-vn` case `co-case-cd2e73c5250a` with invoice `GIN01425L031` still loads `Demo tự nạp` because Data Hub returns `0` invoice matches for that invoice.
- Data Hub invoice `GUS28826A131-3F` was verified to match one reviewed E42 row for `growatt-vn`.
- Data Hub API request artifact for BCCT market inference is ready at `.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md`.
- UI screenshots for this dossier polish session are under `.ai/screenshots/co-dossier-polish/`.
- Pre-existing untracked discovery artifacts remain separate unless the user explicitly asks to commit them:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`

## Recent Changes
- Updated `app/co_case_store.py` to auto-generate case codes and safely resolve stored supporting files.
- Updated `app/main.py` with C/O workflow status labels and a supporting-file download route.
- Reworked `app/templates/co_case.html` so origin evaluation is read-first, carries snapshot fields through hidden inputs, and uses Vietnamese status copy instead of "coming soon" UI text.
- Added CSS for workflow statuses and compact origin product strips in `app/static/css/app.css`.
- Added regression tests in `tests/test_co_demo.py` for generated case codes, step status labels, supporting-file download, and removal of edit-heavy origin inputs/evidence export action.
- Created `.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md` requesting Data Hub to add `unloading_location`, consignee/date/shipping fields, and `market_hint` to `/v1/hub/bcct/invoice-matches`.

## Verification
- `uv run pytest -q` passed: 145 tests.
- `git diff --check` passed.
- Playwright screenshots captured desktop/mobile C/O dossier views under `.ai/screenshots/co-dossier-polish/`.
- Temporary no-auth CO screenshot server on port `8002` was stopped after checks.

## Next Steps
1. Wait for Data Hub approval/implementation of `.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md`.
2. After Data Hub implements the contract, consume only through `app/data_hub_client.py` and infer market from item-level `market_hint`; require operator confirmation on missing/conflicting hints.
3. Re-test `growatt-vn` invoices against Data Hub after market fields are exposed; `GIN01425L031` currently does not match Data Hub rows, while `GUS28826A131-3F` does.
4. Continue replacing remaining preview/demo origin calculation with real legal PSR engine, allocation ledger, and durable case-level Data Hub BOM binding.

## Notes for Next AI Session
- User writes Vietnamese casually; reply in fully accented Vietnamese when the user writes Vietnamese.
- User strongly dislikes confusing/card-heavy UI. Prefer compact operator flows, sparse copy, and clear data hierarchy.
- Do not reintroduce criteria workbook upload in the C/O origin tab; criteria must be system-generated.
- Demo data in the origin tab is intentionally view-context only and labeled `Demo tự nạp`; it should not silently persist into case records or export outputs.
- Do not infer C/O market from `destination_location_name` values like `CANG LACH HUYEN HP`; those are Vietnam-side logistics locations. The useful field is `unloading_location` such as `USLAX`, `INMAA`, or `INNSA`.
- Keep Data Hub API literals inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- Do not commit or modify the pre-existing untracked `.ai/features/...` and `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md` files unless asked.
