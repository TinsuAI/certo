# Project Status

## Current State
- Active branch: `sprint/co-case-supporting-files-20260429`.
- The FastAPI/Jinja C/O demo now has a first persisted C/O dossier workflow for each client: create/open case, store invoice and bill of lading metadata, upload supporting files, match BCCT export rows by invoice, show form guidance, preview a draft criteria table, and export a dossier workbook.
- The first focused forms are covered as source-backed advisory guidance: Form B, Form AI, Form CPTPP, and Form EUR.1. The app deliberately does not infer final HS-specific PSR criteria yet; rows stay in "needs PSR lookup" status until a legal rule engine exists.
- Growatt has a prepared local test case in the temp runtime store: `TEST-AI-GIN01424L171`, invoice `GIN01424L171`, destination `An Do`, URL `/clients/growatt/co-case/co-case-1d5ef62b0f86`.
- Runtime data remains local-only under `data/local/...`; manual test data for this session is isolated under ignored `temp/user-test/co-cases`.

## Recent Changes
- Added `.ai/features/2026-04-29-co-dossier-supporting-files-and-form-guidance.md` documenting the feature scope, domain verification, risks, and open questions.
- Added `app/co_case_store.py` for file-backed C/O cases, supporting-file storage, invoice matching against reviewed BCCT export rows, criteria preview rows, and dossier XLSX export.
- Added `app/co_forms.py` for market-to-form advisory guidance for B, AI, CPTPP, and EUR.1 with source/instrument metadata.
- Updated `app/main.py` and `app/templates/co_case.html` to support case creation/detail routes, supporting-file upload, persisted shipment metadata, invoice match display, form guidance, criteria preview, and dossier workbook export.
- Updated `app/demo_data.py` so form evaluation preserves persisted case ids and shipment metadata.
- Expanded `tests/test_co_demo.py` with regression tests for case creation/selection, invoice matching, persistence after evaluate, reviewed-export filtering, upload validation, form guidance, workbook export, and filename sanitization.

## Next Steps
1. User manual test is still pending. Start with `http://127.0.0.1:8001/clients/growatt/co-case/co-case-1d5ef62b0f86` if the detached server is still running.
2. Exercise the full dossier flow in the browser: create case, change invoice, change destination market, upload supporting file, reject invalid upload, and export XLSX.
3. Build the real legal PSR/HS lookup model before showing any final origin pass/fail conclusion by form.
4. Add OCR or document parsing only after deciding how invoice/BL/supporting files should become structured evidence.
5. Replace the current criteria preview with real allocation/consumption logic when C/O stock allocation moves beyond demo display.

## Notes for Next AI Session
- Tests last passed in this session with `uv run pytest tests/test_co_demo.py -q`: `73 passed`.
- `git diff --check` was clean before handoff verification.
- A detached dev server was started for user testing at `http://127.0.0.1:8001` with `CO_CASE_STORE_ROOT=/home/vp/workspace/client/barry-CO-main/temp/user-test/co-cases`; PID/log are in `temp/user-test/server.pid` and `temp/user-test/server.log`.
- Earlier server attempts died because they were started inside an interactive tool session; the app did not crash. Uvicorn logged clean shutdown with no stack trace. Use detached/no-reload for user testing.
- Do not commit `data/` runtime state or `temp/` screenshots/uploads unless the user explicitly asks for sanitized fixtures.
- User prefers Vietnamese replies when writing Vietnamese; project docs and handoff artifacts stay in English unless client-facing.
