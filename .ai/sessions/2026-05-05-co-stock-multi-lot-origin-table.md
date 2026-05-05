# Session: CO Stock Multi-Line Allocation And Origin Table UX

Date: 2026-05-05

## What Was Done

- Implemented snapshot-only allocation across multiple CO stock source lines.
  - Added a case-level allocation pool so material rows can consume more than one source line in deterministic order.
  - Added allocation detail rows containing declaration/line, source row, available/remaining quantity, allocated quantity, unit value, currency, material value, description, HS code, and valuation source.
  - Added shortage handling and mixed-currency review behavior so invalid VNM totals are not silently calculated.
- Updated persistence and export surfaces.
  - Origin hidden form data now round-trips `allocation_lines`.
  - `Origin Snapshot` includes allocation rows.
  - `LVC Statement` includes allocation detail columns and emits allocation-level rows when present.
- Reworked the origin table UI.
  - Visible Vietnamese wording now uses “dòng tồn” instead of “lot”.
  - Parent material rows show compact data/source chips.
  - Allocation detail renders as child rows, collapsed by default for clean rows and expanded for warning/shortage rows.
  - `Tên NVL` is line-clamped and the table uses horizontal scrolling on narrow viewports instead of squeezing columns.
- Added Demo Precision Manufacturing VN data for manual review.
  - Demo case URL: `http://127.0.0.1:8001/clients/demo-precision-manufactu-480e/co-case/co-case-b38e3da478f0/origin`
  - Case code: `CO-DEMO-DONG-TON`
- Added a future grid-library spike at `.ai/features/2026-05-05-origin-table-grid-library-spike.md`.
  - Recommendation: keep native HTML for this sprint; evaluate Tabulator first for future editable workbook-style tables.
- Captured local Puppeteer screenshots under `.ai/screenshots/co-case-origin-ux/` to verify compact chips and horizontal scroll behavior.
- Verification:
  - `uv run pytest tests/test_co_demo.py::test_co_case_origin_round_trips_multi_lot_allocation_to_export_workbook` passed.
  - `uv run pytest` passed with `169 passed in 29.74s`.
  - `curl -fsS http://127.0.0.1:8001/healthz` returned `{"status":"ok"}`.

## Decisions Made

- Use “dòng tồn” in Vietnamese UI instead of “lot” because the business concept is a stock/source line, not an English warehouse lot.
- Keep allocation snapshot-only in CO for now. Global reservation/trừ tồn across dossiers requires a ledger decision and likely a Data Hub-owned contract.
- Collapse child allocation rows by default to keep the origin table dense, but auto-expand rows with issues so shortage/valuation problems remain visible.
- Prefer horizontal scroll plus stable column widths over squeezing `Tên NVL`; this avoids tall rows on narrow viewports.
- Keep native HTML table for this sprint. Tabulator is the first candidate for a future editable-grid POC because it fits the current server-rendered app better than headless TanStack Table and avoids committing to AG Grid licensing before feature validation.

## What Didn't Work

- Showing all source-line details inside the last parent cell made every material row too tall and noisy.
- The first compact chip pass still looked cramped because the full status text `Đủ evidence tính VNM` consumed too much width. The visible label was shortened to `Đủ dữ liệu` while preserving the full label in the title and hidden form data.
- Browser screenshots against port `8001` redirected to login because auth is enabled. A temporary `CO_AUTH_REQUIRED=0` server on port `8002` was used for screenshots and then stopped.

## Open Items

- User should review the Demo Precision origin page and decide whether the collapsed child-row UX works for daily operation.
- If editable workbook behavior becomes near-term, run a Tabulator POC with validation, keyboard navigation, copy/paste, frozen columns, and expandable allocation detail.
- Decide whether shared stock reservation across dossiers is required before implementing any global decrement behavior.
- Revisit mixed-currency allocation rules before automatically summing VNM across currencies.
- Local uncommitted artifacts remain outside the intended commit:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
  - `.ai/screenshots/co-case-origin-ux/`
