# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; latest health check returned `200`.
- Local Data Hub is running at `http://127.0.0.1:8754`; latest health check returned `200`.
- CO dev is using Postgres for workflow/case state and stock ledger:
  - local ignored `.env`: `BARRY_DATABASE_URL=postgresql:///barry_co?host=/var/run/postgresql`, `BARRY_DATABASE_SCHEMA=co`
  - use `uv run --env-file .env ...` for DB-backed live-state checks
- Full Python suite passes: `uv run pytest` -> `219 passed, 1 skipped, 7 warnings`.
- `git diff --check` passes.
- `npm test` still has pre-existing legal lookup failures around missing `raw-binary` source links; this is outside the CO bảng kê flow.
- Untracked screenshot directories and `.ai/sister-app-prompts/` are local artifacts and should stay out of commits unless explicitly requested.

## Recent Changes
- TKX/TKN tab now checks actual uploaded declaration files, not BCCT row presence:
  - CO consumes Data Hub `GET /v1/hub/clients/{client_id}/declarations` through `app/data_hub_client.py`
  - `case_tkx_tkn_summary()` uses `file_count > 0` for `Đã có` vs `Thiếu tờ khai`
  - Data Hub API request artifact added at `.ai/api-requests/2026-05-15-declaration-file-status.md`
- Added TKX/TKN bulk download links in the XNK tab:
  - `TKX_<shipment_export_declaration_no>.zip`
  - `TKN_CO_<shipment_export_declaration_no>.ZIP`
  - links target Data Hub `/clients/{client_id}/declarations/download.zip`
- Origin/Bảng kê C/O is now lazy-loaded per sheet:
  - opening the Origin tab builds product sheet shells only
  - no BOM/material allocation/LVC calculation happens until the user clicks `Load BOM vào Bảng Kê` for that sheet
  - sheets that have never been loaded remain `draft`/`Chưa tính`; they are no longer marked `stale` just because an earlier sheet changed
  - after `Load BOM`, `Chốt`, or `Mở chốt`, the UI keeps the active sheet tab instead of jumping back to sheet 1
- Local Johnson test case state was cleaned to match the new flow:
  - `MFW0502-571` remains locked
  - later sheets were reset to `draft` with no precomputed material rows

## Next Steps
1. Manually browser-test Johnson case `johnson-vn/co-case-ec000d03522e/origin`: open each sheet, click `Load BOM vào Bảng Kê`, then `Chốt`, and confirm the UI stays on the active sheet.
2. Confirm deployed Data Hub has both declaration contracts used by CO:
   - `GET /v1/hub/clients/{client_id}/declarations`
   - `GET /clients/{client_id}/declarations/download.zip`
3. Browser-test TKX/TKN download links with a logged-in Data Hub session and real uploaded declaration files.
4. Verify the Data Hub `bcct/by-codes` provider endpoint before relying on narrow substitute-stock lookup for Johnson-scale clients.
5. Resolve unrelated `npm test` legal lookup failures around `raw-binary` links before treating Node tests as a release gate.

## Blockers
- CO now depends on the Data Hub declaration status/download routes being present in the Data Hub environment.
- `Form&PSR` remains W.I.P.; rule/evidence engine is not implemented beyond current form/criteria guidance.
- Node legal tests are failing independently of CO workflow changes.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User prefers concise, direct status and expects concrete verification evidence.
- User is sensitive to slow UX and loading without progress. Keep async actions visibly loading and avoid page-level blocking unless necessary.
- User expects CO dev to use Postgres. Do not add new JSON persistence for workbook/ledger state.
- Current running CO server is a background `npm run co:serve` process writing logs to `/tmp/barry-co-8001.log`.
- Local Data Hub server logs are at `/tmp/data-hub-8754.log`.
