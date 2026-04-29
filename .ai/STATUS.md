# Project Status

## Current State
- Active branch: `sprint/co-case-supporting-files-20260429`.
- The FastAPI/Jinja C/O demo now treats C/O as the primary shipment workflow, not as a peer data tab.
- `/clients/{client_id}/co-case` is now only the C/O workflow entry: create a dossier and choose from a structured dossier list.
- A selected dossier shows workflow steps under `/clients/{client_id}/co-case/{case_id}` and `/clients/{client_id}/co-case/{case_id}/{step}`:
  - `shipment`
  - `documents`
  - `exports`
  - `guidance`
  - `origin`
  - `review`
- The dossier list displays title, case code, destination market, invoice, bill of lading, file count, update time, and an `Mở hồ sơ` action. On mobile each dossier renders as a readable stacked record.
- Supporting-file upload redirects back to the `documents` step. Shipment metadata edits use a dedicated `/shipment` POST route so they do not drop origin/product data.
- Growatt manual test is still served at `http://127.0.0.1:8001/clients/growatt/co-case/co-case-1d5ef62b0f86`; the detail URL opens the shipment step.
- Dev server is running in tmux, not systemd: session `1-CO-MAIN`, window `barry-co-dev`, command `npm run co:serve`, with `CO_CASE_STORE_ROOT=/home/vp/workspace/client/barry-CO-main/temp/user-test/co-cases`.
- The app still does not infer final HS-specific PSR criteria. Form rows correctly remain in `needs_rule_lookup` until a legal rule engine exists.

## Recent Changes
- Added discovery brief `.ai/features/2026-04-29-co-workflow-navigation-redesign.md`.
- Promoted C/O to a primary workflow entry in `_client_nav.html`; data modules remain as supporting company data surfaces.
- Redesigned `co_case.html`:
  - index view is create/open + dossier list only
  - detail views show the selected dossier stepper and step-specific content
  - index no longer shows workflow stages, BOM snapshot, source snapshot, origin evaluation, or criteria preview
- Added C/O workflow step routing and validation in `app/main.py`.
- Added dedicated shipment metadata update route: `POST /clients/{client_id}/co-case/{case_id}/shipment`.
- Updated workspace overview copy to present C/O as the main workflow and catalog/BOM/stock/BCCT/config as supporting data.
- Expanded Python regression coverage for:
  - C/O promoted out of peer data tabs
  - index-only dossier list behavior
  - selected-dossier workflow step URLs
  - supporting upload returning to `documents`
  - shipment metadata save without losing origin/product view
  - snapshot assertions living inside opened dossier steps, not the index
- Verified UI with Playwright desktop/mobile smoke tests for index/detail behavior and no horizontal overflow.

## Next Steps
1. User manual browser test: open the Growatt case URL, use the new workflow steps, upload the prepared files by slot, confirm expected accepts/rejects, and export the dossier XLSX.
2. Capture any UI/domain issues from the manual test before adding more dossier functionality.
3. Resolve or intentionally rebaseline the 3 known failing Node legal lookup tests so project-level `npm test` is trustworthy again.
4. Define the structured PSR/HS legal rule lookup model before showing final origin pass/fail by form.
5. Replace the current criteria preview with real stock allocation/reservation semantics after the dossier workflow is validated.

## Blockers
- `npm test` still fails 3 known legal lookup `raw-binary` source-link expectations in `tests/legal-lookup-server.test.mjs`; this is unrelated to the C/O workflow redesign.

## Notes for Next AI Session
- Current C/O Python verification: `uv run pytest tests/test_co_demo.py -q` passed with `75 passed`.
- UI smoke verification used Playwright against `http://127.0.0.1:8001` for desktop and mobile C/O index/detail pages and passed.
- Last `npm test` run still had the same 3 known legal lookup failures documented above.
- Current dev server should be visible in tmux: `tmux attach -t 1-CO-MAIN`, then switch to window `barry-co-dev`.
- The user wants the dev server kept running in a visible tmux session, not as a hidden systemd service.
- Manual test files remain under ignored `temp/user-test/manual-files`; the input sheet is `temp/user-test/MANUAL_TEST_INPUTS.md`.
- Do not commit `data/` runtime state or `temp/` uploads/screenshots unless the user explicitly asks for sanitized fixtures.
- User prefers Vietnamese replies when writing Vietnamese; project docs and handoff artifacts stay in English unless client-facing.
