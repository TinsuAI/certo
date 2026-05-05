# Project Status

## Current State
- Active branch: `main`; latest session work is captured in handoff artifacts and intended for a local commit. Do not push unless the user asks.
- Local CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returned `{"status":"ok"}` on 2026-05-05. With auth enabled, unauthenticated app pages redirect to `/auth/login`.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- The C/O origin page now supports snapshot-only multi-line stock allocation:
  - one material can consume multiple CO stock source lines in deterministic order
  - allocation lines round-trip through hidden form fields
  - XLSX export includes allocation detail in `Origin Snapshot` and `LVC Statement`
  - shortage and mixed-currency cases stay review-only instead of silently summing invalid values
- The origin material table is now compact:
  - parent rows show a concise data-status badge plus source/allocation chip
  - stock source lines render as child rows and are collapsed by default unless the row has an issue
  - `Tên NVL` is line-clamped and the table uses horizontal scrolling on narrow viewports
- Demo Precision Manufacturing VN has a demo C/O case for reviewing multiple stock source lines:
  - `http://127.0.0.1:8001/clients/demo-precision-manufactu-480e/co-case/co-case-b38e3da478f0/origin`
  - case code: `CO-DEMO-DONG-TON`
- A library spike for future editable workbook-like tables exists at `.ai/features/2026-05-05-origin-table-grid-library-spike.md`; current recommendation is to keep native HTML for this sprint and evaluate Tabulator first for a future editable-grid POC.
- Pre-existing unrelated worktree artifacts remain separate and should not be committed unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
- Local screenshot artifacts remain under `.ai/screenshots/co-case-origin-ux/`; they were used for visual verification and are not required for the commit.

## Recent Changes
- Implemented CO stock allocation across multiple source lines:
  - added an allocation pool and deterministic source-line consumption helpers
  - enriched origin material snapshots with `allocation_lines`, status, shortage quantity, source refs, allocation summaries, and line-level material values
  - preserved BCCT source line IDs, declaration/line numbers, remaining quantities, unit values, currencies, descriptions, and HS codes
- Updated origin snapshot persistence/export:
  - hidden form data now carries allocation lines through POST/export
  - `Origin Snapshot` records allocation rows
  - `LVC Statement` expands allocation detail columns and outputs one row per material allocation line
- Reworked origin UI language and density:
  - replaced visible “lot” wording with “dòng tồn”
  - added expandable child rows for stock source lines
  - collapsed clean allocation rows by default, while warning/shortage rows stay expanded
  - compacted the source/status cell and added horizontal scroll for wide tables
- Added Demo Precision Manufacturing VN data covering multiple stock source-line scenarios, including mixed-currency and shortage review cases.
- Added focused regression tests for multi-line allocation, mixed currency handling, hidden form round-trip, workbook export, demo case availability, and the compact/collapsed UI markers.
- Verification completed:
  - `uv run pytest tests/test_co_demo.py::test_co_case_origin_round_trips_multi_lot_allocation_to_export_workbook` passed
  - `uv run pytest` passed: `169 passed in 29.74s`
  - Puppeteer screenshots confirmed compact chips and horizontal scroll behavior on desktop/narrow viewports

## Next Steps
1. Have the user manually review the Demo Precision origin page and decide whether collapsed child rows are acceptable for daily review.
2. If staff editing becomes a near-term requirement, run a small Tabulator POC against the origin table with validation, keyboard navigation, copy/paste, frozen columns, and expandable allocation detail.
3. Decide whether global stock reservation across dossiers is required. If yes, design/approve a ledger, likely Data Hub-owned, before decrementing shared stock globally.
4. Revisit mixed-currency allocation rules before automatically summing VNM across currencies.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: briefly say what was inspected, what failed, and how it was resolved.
- Current allocation behavior is snapshot-only inside CO. It consumes a mutable in-memory pool while building a case snapshot, but it does not reserve or decrement shared stock across dossiers.
- The term to use in Vietnamese UI is “dòng tồn”, not “lot”.
- Puppeteer visual checks used a temporary `CO_AUTH_REQUIRED=0` server on port `8002`; that temporary server was stopped. The regular dev server remains on port `8001`.
- Do not commit the unrelated `docs/co-form-index-confirmation.*` changes unless the user explicitly asks.
