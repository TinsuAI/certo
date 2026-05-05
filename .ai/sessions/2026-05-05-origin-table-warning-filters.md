# Session: Origin Table Column And Warning Filters

Date: 2026-05-05

## What Was Done

- Added collapsible optional columns to the origin material table.
  - Operators can hide/show `HS`, `Định mức`, `Lượng dùng`, `Đơn giá`, `Trị giá`, `Xuất xứ`, `KXX/VNM`, and `Nguồn`.
  - Column visibility is stored in browser `localStorage`, so it persists across product sheets and reloads in the same browser.
  - The table recalculates its minimum width when columns are hidden, reducing horizontal scroll instead of just hiding text.
- Added filterable warning summary chips.
  - `origin-warning-summary` items are now buttons.
  - Clicking a warning filters the current product sheet to material rows matching that warning kind.
  - Allocation child rows follow their parent material row, so source-line context stays visible after filtering.
  - `Tất cả dòng` clears the active warning filter.
- Verified the warning filter in the browser.
  - On Demo Precision sheet 2, clicking `Thiếu tồn CO` filtered from 3 NVL rows to 1 matching NVL row plus 2 allocation child rows.
  - Screenshot saved locally at `.ai/screenshots/co-case-origin-ux/origin-warning-filter.png`.
- Verification:
  - `uv run pytest` passed with `169 passed in 28.28s`.
  - `curl -fsS http://127.0.0.1:8001/healthz` returned `{"status":"ok"}`.

## Decisions Made

- Warning filtering is single-select for now. Click one warning to focus, click it again or `Tất cả dòng` to clear.
- Warning filtering is scoped to the current product sheet, not global across all sheets, because each sheet has its own warning summary and table.
- The filter hides rows with a CSS class (`origin-row-filtered`) instead of deleting DOM rows, preserving hidden form inputs and export behavior.
- Child allocation rows are filtered by parent material group, not by their own warning state.

## What Didn't Work

- The first Puppeteer check tried to click a warning in the initially active sheet, but Demo Precision warnings were on sheet 2. The check was corrected to activate the first sheet containing warning filters before clicking.
- Full table detail inside the last cell had already proven too dense earlier; the current UX keeps parent rows compact and uses row-level details plus filters.

## Open Items

- Decide whether warning filters should support multi-select later.
- Consider adding a visible active-filter count if real customer files have many warning chips.
- Keep unrelated local artifacts out of commits unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
  - `.ai/screenshots/co-case-origin-ux/`
