# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; unauthenticated curl redirects to `/auth/login`.
- A sibling Data Hub dev server is still running at `http://127.0.0.1:8754`.
- CO remains a Data Hub consumer in local runtime mode. Data Hub-owned catalog, BCCT, and BOM upload surfaces are hidden/blocked in Data Hub mode; CO still owns C/O case workflow files and generated outputs.
- UI/data workflow redesign is implemented for the client data modules and C/O case workflow:
  - data tables now use compact filter/search/pagination UI via the shared advanced table component
  - BOM view opens by finished product first and then shows that product's BOM lines
  - C/O case entry is simplified around invoice -> searchable market -> suggested form/instrument -> HS criteria
  - origin tab no longer uploads a criteria workbook; it presents system-generated criteria from invoice/BCCT/BOM context
  - origin tab preloads a clearly labeled demo dataset when a case has no invoice/BCCT/BOM data yet
- UI screenshots for this session are under `.ai/screenshots/co-data-ui-redesign/`.
- Pre-existing untracked discovery artifacts remain separate unless the user explicitly asks to commit them:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`

## Recent Changes
- Added namespaced query handling and link-cell support to `app/table_view.py` and `_advanced_table.html`.
- Restyled data-heavy UI surfaces in `app/static/css/app.css` to be flatter, denser, and easier to scan.
- Reworked `app/templates/bom.html` so users choose a finished product and then view the BOM for that product, with Data Hub read-only treatment preserved.
- Expanded `app/co_forms.py` with market/form presets for Form B, CPTPP, EUR.1, and AI, including common market shortcuts and HS criteria previews for 8504/8541.
- Added C/O case default form inference in `app/co_case_store.py`.
- Extended C/O context in `app/main.py` to derive form lanes, invoice-matched HS criteria rows, and an origin-tab demo context.
- Rebuilt `app/templates/co_case.html` around the requested flow: create/open case, enter invoice, choose searchable market, see suggested form/instrument, then review HS criteria by product.
- Removed upload controls from the origin tab; the tab now explicitly says the criteria table is system-generated, not operator-uploaded.
- Added regression tests in `tests/test_co_demo.py` for searchable market/form guidance, invoice-to-HS criteria mapping, hidden origin upload controls, and origin demo preload behavior.

## Verification
- `uv run pytest -q` passed: 144 tests.
- `git diff --check` passed.
- Playwright screenshots were captured for desktop/mobile C/O case and origin-tab views.
- Temporary no-auth screenshot server on port `8002` was stopped after browser checks.

## Next Steps
1. Continue replacing remaining wide/edit-heavy origin grids with read-first system tables where possible.
2. Wire the legal PSR engine and allocation ledger behind the existing preview UI so "coming soon" rows become traceable rule decisions.
3. Persist case-level Data Hub BOM version selections instead of only adapting the read workspace.
4. Revisit mobile top navigation height separately if the user wants the first viewport even tighter.

## Notes for Next AI Session
- User writes Vietnamese casually; reply in fully accented Vietnamese when the user writes Vietnamese.
- User strongly dislikes confusing/card-heavy UI. Prefer compact operator flows, sparse copy, and clear data hierarchy.
- Do not reintroduce criteria workbook upload in the C/O origin tab; user clarified that criteria must be system-generated.
- Demo data in the origin tab is intentionally view-context only and labeled `Demo tự nạp`; it should not silently persist into case records or export outputs.
- Keep Data Hub API literals inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- Do not commit or modify the pre-existing untracked `.ai/features/...` and `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md` files unless asked.
