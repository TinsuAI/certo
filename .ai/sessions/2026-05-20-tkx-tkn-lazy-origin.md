# 2026-05-20 — TKX/TKN Declaration Files And Lazy Origin Sheets

## What Was Done
- Reworked TKX/TKN/XNK status so it answers whether uploaded declaration files exist, not whether the declaration appears in BCCT.
  - Added `DataHubClient.list_declarations()` and `DataHubPortfolioService.declaration_file_counts()`.
  - Passed `source_context["declaration_file_counts"]` into `case_tkx_tkn_summary()` and dossier ZIP export.
  - Updated XNK tab copy from “Data Hub/BCCT presence” to “file tờ khai presence”.
- Added Data Hub API request artifact for declaration status and download ZIP contract:
  - `.ai/api-requests/2026-05-15-declaration-file-status.md`
  - Data Hub implementation was done in the sibling Data Hub repo by the user/other side, not by CO.
- Added TKX/TKN bulk download buttons in the XNK tab:
  - export: `TKX_<shipment_export_declaration_no>.zip`
  - import: `TKN_CO_<shipment_export_declaration_no>.ZIP`
  - links point to Data Hub cookie-session route `/clients/{client_id}/declarations/download.zip`.
- Investigated why Johnson origin sheet 2 “could not chốt”.
  - Server-side route worked after `Load BOM`; the immediate issue was state/UX: sheet 2 was `stale`, so direct `Chốt` was blocked until recalculation.
  - UI also jumped back to sheet 1 after AJAX shell replacement, making successful actions on later sheets look like they did not stick.
- Changed Origin/Bảng kê flow to lazy-load per sheet:
  - Origin GET now builds product sheet shells only via `prepare_case_origin_product_shells()`.
  - BOM rows, material allocations, stock consumption, and LVC are calculated only by `prepare_case_origin_sheet()` when the user clicks `Load BOM vào Bảng Kê`.
  - `mark_origin_sheets_stale()` now leaves untouched draft sheets as `draft` instead of marking them `stale`.
  - AJAX sheet actions preserve the active product tab after shell replacement.
- Cleaned the local Postgres state for Johnson case `co-case-ec000d03522e` so it matches the new workflow:
  - first sheet `MFW0502-571` remains locked
  - later sheets are draft with no precomputed material rows
- Updated regression tests for the new lazy-load behavior and Data Hub declaration contract.

## Decisions Made
- “Có/thiếu TKX/TKN” must be based on `hub.customs_declaration_files.file_count`, not BCCT rows.
- CO consumes declaration status through `app/data_hub_client.py`; no raw `/v1/hub/*` calls were added outside the adapter.
- Data Hub owns ZIP file content and manifest generation. CO only renders browser links to the Data Hub route.
- Origin sheet calculation should be explicit per sheet. Opening Origin should not precompute every sheet, because that creates confusing stale states and unnecessary heavy work.
- A sheet that has never been loaded should remain `draft`; `stale` is reserved for a sheet that had calculated/chốt data and is now invalidated by earlier changes.
- The active sheet tab should survive AJAX shell replacement for calculate/lock/reopen actions.

## What Didn't Work
- Implementing the Data Hub endpoint directly from CO violated the project rule. Those Data Hub edits were rewound, and the request artifact was used instead.
- Reading Johnson state without `uv run --env-file .env` used non-DB/demo state and produced misleading results. Live CO state must be inspected with the local Postgres `.env`.
- Backend-only checks showed `Load BOM` then `Chốt` worked, but they did not catch the UX confusion where the shell jumped back to sheet 1. The UI needed tab preservation after replacement.
- Earlier tests expected Origin GET to calculate BOM/NVL rows immediately. Those tests were updated to assert shell-only GET and material rows only after sheet calculate.

## Open Items
- Manually browser-test the Johnson case with the new flow:
  - open sheet 2
  - click `Load BOM vào Bảng Kê`
  - confirm it becomes `calculated`
  - click `Chốt`
  - confirm tab stays on sheet 2 and later sheets remain `draft` until loaded
- Verify Data Hub declaration ZIP route with real uploaded declaration files and a logged-in operator session.
- Confirm Data Hub declaration status/download routes are deployed anywhere CO will be tested.
- `bcct/by-codes` provider verification remains pending for Johnson-scale substitute-stock performance.
- `npm test` legal `raw-binary` failures remain unrelated and unresolved.
