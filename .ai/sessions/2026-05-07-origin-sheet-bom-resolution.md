# Session: Origin Sheet Workflow and BOM Product Resolution

## What Was Done
- Reworked the origin calculation workflow from one global snapshot action to sheet-level actions:
  - removed global `Tính lại snapshot`,
  - added per-sheet `Tính bảng kê`,
  - added per-sheet `Chốt/Mở chốt`,
  - persisted `origin_sheet_states`,
  - added autosave for sheet order/input changes,
  - made changed/current and downstream sheets stale,
  - blocked export from posted origin form data when sheets are stale/draft/calculating.
- Replaced drag/drop sheet ordering with left/right arrow controls on the sheet tabs. The sheet tabs are now the user-visible source of order.
- Redesigned the per-sheet toolbar so status, BOM TP selection, `Tính bảng kê`, and `Chốt/Mở chốt` sit together in one compact row under the product header.
- Investigated the Growatt `BIENTAN.17` BOM empty issue:
  - Data Hub BCCT rows expose `customs_code/internal_code = BIENTAN.17`,
  - actual BOM code `PV01.0117500` appears only inside `goods_name`,
  - Data Hub BOM artifacts are keyed by `PV01.0117500`, not `BIENTAN.17`,
  - `code-mappings` exists but is many-to-many and is not a safe source of truth.
- Added a temporary CO-side bridge so the current Growatt case can load BOM rows:
  - Data Hub BOM service fetches explicitly requested filtered product codes directly instead of relying on `/products` pagination,
  - CO can use `code-mappings` as a temporary candidate bridge,
  - existing persisted products can be rebuilt from current product rows when invoice matches are unavailable.
- Created and reviewed Data Hub API request:
  - `.ai/api-requests/2026-05-07-bcct-bom-product-resolution.md`
  - The request asks Data Hub to add item-level `product_identity` to BCCT and invoice-match rows.
- Added tests covering:
  - direct filtered Data Hub BOM fetch,
  - customs/display product code resolving to a BOM product candidate,
  - sheet-level toolbar markers,
  - autosave stale state,
  - sheet calculate/lock state,
  - stale sheet export blocking.
- Verification:
  - targeted regression tests passed,
  - full suite passed: `uv run pytest` -> `183 passed in 28.37s`,
  - Data Hub context check for `growatt-vn` resolved `BIENTAN.17 -> PV01.0117500` and loaded 274 BOM rows,
  - TestClient sheet calculate smoke returned 200 and rendered `PV01.0117500`, `274 dòng`, and material hidden inputs.

## Decisions Made
- Sheet ordering should use arrow buttons on tabs, not drag/drop. The interaction is explicit and clearer for the user.
- The global origin recalculation button should remain removed. Calculation is now a per-sheet workflow action.
- Sheet status is stored as origin-preparation state in the CO case record under `origin_sheet_states`; it is not a final dossier status.
- `calculated` is enough to clear export blockers for draft workbook export; `locked` is available as a stronger user acceptance state.
- CO can keep per-case manual BOM TP overrides, but those overrides must not become global Data Hub truth without a separate approved mutating contract.
- Long-term BOM product identity resolution belongs in Data Hub, not CO. CO should consume `product_identity.bom_product_code` only when Data Hub returns `resolution_status == "resolved"`.
- `code-mappings` is candidate evidence only. It must not be treated as authoritative line-level identity because it can be many-to-many.
- Customer-specific parsing, such as Growatt extracting `PV01...` from `goods_name`, belongs in Data Hub parser/resolver adapters.

## What Didn't Work
- Drag/drop sheet ordering was not visually clear enough for the user, so it was removed in favor of arrow buttons.
- Direct BOM lookup by `BIENTAN.17` returned no rows because Data Hub BOM artifacts are keyed by `PV01.0117500`.
- Relying on Data Hub `/products` listing to find filtered BOM products was insufficient because the needed product code may not appear in the first page/list response.
- Using `code-mappings` as the long-term fix is unsafe and overfit-prone. It unblocks current CO behavior but should be removed after Data Hub implements `product_identity`.
- Automated UI screenshot verification could not run because the environment does not have Playwright/Chromium installed.

## Open Items
- Mirror the Data Hub API request into the Data Hub repo or issue tracker so Data Hub can implement it.
- Data Hub should implement provider tests for `product_identity`, especially Growatt `goods_name` containing `(PV01.0117500)`.
- After Data Hub approval and implementation, CO should remove temporary `code-mappings` BOM resolution and consume the approved `product_identity` contract.
- Re-check the sheet toolbar in a real authenticated browser session.
- Decide whether duplicate finished-product codes can occur in one dossier. If yes, replace product-code keyed sheet state with declaration/line/code identity.
