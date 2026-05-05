# Project Status

## Current State
- Active branch: `main`; recent origin-table UX work is captured in local commits. Do not push unless the user asks.
- Local CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returned `{"status":"ok"}` on 2026-05-05. With auth enabled, unauthenticated app pages redirect to `/auth/login`.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- The C/O origin page now supports snapshot-only multi-line stock allocation:
  - one material can consume multiple CO stock source lines in deterministic order
  - allocation lines round-trip through hidden form fields
  - XLSX export includes allocation detail in `Origin Snapshot` and `LVC Statement`
  - shortage and mixed-currency cases stay review-only instead of silently summing invalid values
- The origin material table is now compact and operator-filterable:
  - parent rows show concise data/source chips
  - stock source lines render as child rows and are collapsed by default unless the row has an issue
  - `Tên NVL` is line-clamped and the table uses horizontal scrolling on narrow viewports
  - optional columns can be hidden/shown with the `Cột` controls; state is stored in browser `localStorage`
  - warning summary chips filter the table to matching NVL rows, keeping matching allocation child rows visible
- Demo Precision Manufacturing VN has a demo C/O case for reviewing multiple stock source lines and warning filtering:
  - `http://127.0.0.1:8001/clients/demo-precision-manufactu-480e/co-case/co-case-b38e3da478f0/origin`
  - case code: `CO-DEMO-DONG-TON`
- A library spike for future editable workbook-like tables exists at `.ai/features/2026-05-05-origin-table-grid-library-spike.md`; current recommendation is to keep native HTML for this sprint and evaluate Tabulator first for a future editable-grid POC.
- Pre-existing unrelated worktree artifacts remain separate and should not be committed unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
- Local screenshot artifacts remain under `.ai/screenshots/co-case-origin-ux/`; they were used for visual verification and are not required for the commit.

## Recent Changes
- Commit `61a9ef4` implemented CO stock allocation across multiple source lines and XLSX/export round-trip support.
- Commit `a625210` added origin table column controls for hiding/showing optional columns.
- Current handoff session added filterable origin warning summary chips:
  - warning summary items are now buttons with stable warning kinds
  - clicking a warning filters the current product sheet to matching material rows
  - allocation child rows follow the visible/hidden state of their parent material row
  - `Tất cả dòng` clears the warning filter
- Verification completed:
  - `uv run pytest` passed: `169 passed in 28.28s`
  - Puppeteer confirmed `Thiếu tồn CO` filters Demo Precision sheet 2 from 3 NVL rows to 1 matching NVL row plus its 2 allocation child rows
  - temporary auth-disabled screenshot server on port `8002` was stopped

## Next Steps
1. Have the user manually review the Demo Precision origin page and decide whether warning-filter chips should support multi-select, or whether single-select is enough.
2. If staff editing becomes a near-term requirement, run a small Tabulator POC against the origin table with validation, keyboard navigation, copy/paste, frozen columns, and expandable allocation detail.
3. Decide whether global stock reservation across dossiers is required. If yes, design/approve a ledger, likely Data Hub-owned, before decrementing shared stock globally.
4. Revisit mixed-currency allocation rules before automatically summing VNM across currencies.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: briefly say what was inspected, what failed, and how it was resolved.
- Current allocation behavior is snapshot-only inside CO. It consumes a mutable in-memory pool while building a case snapshot, but it does not reserve or decrement shared stock across dossiers.
- The term to use in Vietnamese UI is “dòng tồn”, not “lot”.
- Warning summary filtering is intentionally per product sheet and single-select for now.
- Column visibility is stored in browser `localStorage` key `barryCo.origin.hiddenColumns`.
- Puppeteer visual checks used a temporary `CO_AUTH_REQUIRED=0` server on port `8002`; that temporary server was stopped. The regular dev server remains on port `8001`.
- Do not commit the unrelated `docs/co-form-index-confirmation.*` changes unless the user explicitly asks.
