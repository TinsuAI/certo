# Project Status

## Current State
- Active branch: `main`; do not push unless user asks.
- Local CO dev server is still listening on `http://127.0.0.1:8001`, but auth is enabled there and unauthenticated origin URLs redirect to `/auth/login`.
- Origin workflow now has sheet-level controls instead of one global recalculation action:
  - sheet order is represented by tabs with left/right arrows,
  - global `Tính lại snapshot` is removed,
  - each product sheet has `Tính bảng kê` and `Chốt/Mở chốt`,
  - sheet state is persisted under `origin_sheet_states`,
  - autosave marks changed/current and downstream sheets `stale`,
  - export blocks stale/draft/calculating sheets when exporting from posted origin form data.
- Growatt Data Hub BOM issue was investigated. Current Data Hub BCCT rows for `BIENTAN.17` expose `customs_code/internal_code = BIENTAN.17`; actual BOM code `PV01.0117500` is only embedded in `goods_name`, not a structured field.
- CO has a temporary code path that can use Data Hub `code-mappings` and direct filtered BOM artifact fetches to load BOM rows, but this is intentionally not the desired long-term contract because code mappings can be many-to-many.
- Data Hub API request artifact was created for the correct long-term fix: `.ai/api-requests/2026-05-07-bcct-bom-product-resolution.md`.
- CO remains a Data Hub consumer. Do not add or assume Data Hub endpoints from CO; raw `/v1/hub/*` strings must stay in `app/data_hub_client.py`.

## Recent Changes
- Added feature discovery brief: `.ai/features/2026-05-07-sheet-level-origin-calculation.md`.
- Implemented sheet-level origin state and UI:
  - `origin_sheet_states` persist/restore in case records,
  - per-sheet calculate/lock/reopen/autosave routes,
  - sheet tabs are the visible order source,
  - per-sheet toolbar groups state, BOM TP, `Tính bảng kê`, and `Chốt/Mở chốt`.
- Updated sequential-origin UX and tests to block stale sheet export and preserve stock-allocation behavior.
- Adapted Data Hub BOM workspace fetching so filtered product-code workspaces fetch requested product codes directly instead of depending on `/products` pagination.
- Added temporary BOM-code resolution support from Data Hub `code-mappings` to unblock the Growatt case while waiting for Data Hub product identity resolution.
- Wrote and reviewed the Data Hub proposal for BCCT BOM product identity resolution. Final prompt was provided to the user for Data Hub handoff.
- Verification:
  - `uv run pytest` passed: `183 passed in 28.37s`
  - Live/Data Hub context check for `growatt-vn` resolved `BIENTAN.17 -> PV01.0117500` and loaded 274 BOM rows in CO context.
  - TestClient calculate smoke for `/origin/sheet/BIENTAN.17/calculate` returned 200, showed `PV01.0117500`, `274 dòng`, and no `chưa có BOM`.

## Next Steps
1. Mirror `.ai/api-requests/2026-05-07-bcct-bom-product-resolution.md` into the Data Hub repo/tracker and have Data Hub implement provider tests plus `product_identity` resolver output.
2. After Data Hub provider tests pass, remove CO's temporary `code-mappings`-based BOM resolution and consume only `product_identity.bom_product_code` when `resolution_status == "resolved"`.
3. Re-check the origin sheet toolbar in a real browser session with authenticated `growatt-vn` access; automated screenshot was not possible in this environment because Playwright/Chromium is not installed.
4. Decide whether duplicate finished-product codes can appear in one dossier. If yes, replace product-code keyed sheet state with a stable line identity such as declaration/line/code.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to overfitting and codebase clutter. For Data Hub/CO boundaries, prefer generic contracts and customer-specific parser adapters on the Data Hub side.
- The correct long-term architecture is: Data Hub owns product/BOM identity resolution for BCCT rows; CO owns case workflow and manual per-case overrides only.
- Do not commit unrelated artifacts unless explicitly requested. Currently unrelated local changes include `docs/co-form-index-confirmation.*`, `.ai/screenshots/co-case-origin-ux/`, `.ai/screenshots/co-case-overview-lock/`, and `.ai/sister-app-notes/2026-05-07-bom-presets-3b.md`.
- `.ai/screenshots/co-origin-sequence-lock/` contains UI screenshot artifacts from this work, but they were not required for the final commit unless the user asks to keep screenshots under version control.
