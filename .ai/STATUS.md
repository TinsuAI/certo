# Project Status

## Current State
- Active branch: `main`; current session work is ready to continue from a local commit after handoff. Do not push unless the user asks.
- Local CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returned `{"status":"ok"}` during this session. With auth enabled, unauthenticated app pages redirect to `/auth/login`.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- The C/O origin page now treats the web `Xuất xứ` workbook view as the source snapshot for review/export work:
  - C/O dossier list moved out of the sidebar into the main page with search/filter controls.
  - Origin BOM controls moved into a compact workbar.
  - Each finished product is displayed as an Excel-like sheet tab.
  - The material table scrolls inside the sheet with sticky opaque headers.
- LVC now still shows a temporary percentage when NVL unit prices are missing, with warning styling and tooltip. Missing BOM/NVL still blocks calculation.
- Data Hub BOM consumption now avoids latest `non_flattened` product versions and falls back to the latest usable row-bearing version.
- Origin material names and HS codes now fall back to BCCT import/stock data when BOM/catalog data is missing.
- A discovery brief exists for multi-lot C/O stock allocation: `.ai/features/2026-05-05-co-stock-multi-lot-allocation.md`.
- Pre-existing unrelated worktree artifacts remain separate and should not be committed unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
- Untracked browser smoke screenshots may remain under `.ai/screenshots/co-case-origin-ux/`; they were not committed.

## Recent Changes
- Reworked `/clients/growatt-vn/co-case`:
  - moved dossier list into the main content
  - added search/filter controls for dossier, status, market, and C/O form
  - expanded dossier metadata shown in the list
- Reworked `/clients/growatt-vn/co-case/<case_id>/origin`:
  - compacted BOM snapshot/actions into a workbar
  - removed the large sidebar from the origin workspace
  - added workbook-style product sheet tabs
  - reduced table width pressure by combining related columns
  - replaced repetitive origin warnings with summarized warning chips and per-cell/tooltips
- Fixed origin data quality behavior:
  - LVC returns `partial_pass`, `partial_fail`, or `partial_review` when unit prices are missing but a temporary percentage can be calculated
  - stale hidden-form LVC values are normalized during enrichment
  - missing BOM/NVL stays `missing_bom` and does not show a fake `100%`
  - repeated warning text is deduplicated
- Fixed Data Hub BOM version selection:
  - CO prefers the latest usable flattened/row-bearing product BOM version over a newer `non_flattened` version
  - selected product BOM versions fall back to usable versions when the selected one has no rows
- Improved material source enrichment:
  - BCCT import/stock descriptions and HS codes are preserved into stock rows
  - origin materials fall back through BOM, catalog, then stock data for names and HS codes
  - rows missing material names are highlighted and summarized
- Fixed dark-theme sticky header readability:
  - top navigation and sticky table headers now use opaque surfaces
  - origin material tables use separate border collapse for sticky header coverage
- Added multi-lot allocation discovery:
  - documented the current one-stock-row behavior
  - proposed a phase-one snapshot-only allocation design
  - deferred global reservation/trừ tồn until a ledger/Data Hub contract is approved
- Verification completed:
  - `uv run pytest` passed: `166 passed in 31.31s`
  - HTML smoke on an auth-disabled temporary server confirmed LVC warning cells render `46.98%` and `58.16%` for `co-case-af2895ba8cc6`
  - temporary auth-disabled server on port `8002` was stopped

## Next Steps
1. Implement multi-lot C/O stock allocation using TDD:
   - add a pure allocation helper
   - pass a case-level mutable allocation pool into origin product building
   - add `allocation_lines` to material snapshots and hidden form round-trips
   - update web/XLSX output to show source-line allocation detail
2. Decide whether global stock reservation across dossiers is required. If yes, create/approve a ledger design before implementation, likely Data Hub-owned.
3. Continue exact legacy-style Excel `bảng kê` export from the accepted web `Xuất xứ` snapshot.
4. Revisit mixed-currency handling for VNM before summing multi-lot values across currencies.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: briefly say what was inspected, what failed, and how it was resolved.
- The user accepted deferring multi-lot allocation to the next session because it touches core calculation, snapshot persistence, UI, and XLSX export.
- For multi-lot allocation, phase one should be snapshot-only in CO; do not decrement shared stock globally without an explicit ledger decision.
- Existing source stock rows have `source_row`, `source_line_ids`, `import_declaration_no`, `line_no`, `allocation_code`, `remaining_qty`, `unit_value`, `currency/value_currency`, `hs_code`, and `material_description`.
- Current origin code still assumes one material row maps to one selected source row; this is the main design surface for the next change.
