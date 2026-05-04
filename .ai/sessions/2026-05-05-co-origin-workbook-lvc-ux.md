# Session: C/O Origin Workbook and LVC UX

## What Was Done
- Refreshed the working context and kept the local dev server available at `http://127.0.0.1:8001`.
- Reworked the C/O case index page:
  - moved the dossier list from the sidebar into the main content area
  - added dossier search and filters for status, market, and C/O form
  - expanded the visible metadata for each dossier
- Reworked the origin page for `growatt-vn` C/O cases:
  - moved BOM snapshot selection, selected BOM chips, recalculation, and XLSX export into a compact workbar
  - removed the origin sidebar so the bảng kê area can use the full screen width
  - added Excel-like sheet tabs where each finished product is one sheet
  - made the material table scroll inside the sheet with sticky headers
  - reduced horizontal pressure by combining unit/currency/source/status columns
- Improved origin warnings:
  - deduplicated repeated warning text
  - replaced long repeated warning lists with warning-summary chips
  - added row/cell warning styling and native tooltips for missing material names, missing unit prices, and conservative origin defaults
- Fixed LVC behavior for missing NVL unit prices:
  - LVC now still shows a temporary percentage when it can be calculated from available values
  - missing unit prices produce `partial_pass`, `partial_fail`, or `partial_review` instead of replacing the percentage with only `Thiếu đơn giá NVL`
  - the LVC cell uses warning styling and tooltip text to show the missing-price caveat
  - missing BOM/NVL still blocks calculation and does not show a fake percentage
- Fixed missing material-name causes:
  - BCCT import/stock rows now preserve material description and HS code
  - origin material enrichment falls back through BOM, catalog, and stock data
  - missing names are highlighted and summarized
- Fixed Data Hub BOM fallback:
  - Data Hub BOM service now prefers the latest usable row-bearing product version over newer `non_flattened` versions
  - case BOM attachment and origin row selection fall back to usable product versions when selected versions have no rows
- Fixed dark-theme header readability:
  - top navigation uses an opaque surface
  - sticky table headers use an opaque surface and higher z-index
  - origin material tables use separate border collapse so scrolled rows do not bleed through sticky headers
- Added discovery for multi-lot C/O stock allocation:
  - confirmed current origin code chooses only one best stock row per NVL
  - documented the proposed phase-one snapshot-only allocation design in `.ai/features/2026-05-05-co-stock-multi-lot-allocation.md`
- Verification completed:
  - targeted origin/LVC tests passed
  - full `uv run pytest` passed with `166 passed in 31.31s`
  - auth-disabled HTML smoke confirmed LVC warning cells render temporary values for `co-case-af2895ba8cc6`

## Decisions Made
- Treat the web `Xuất xứ` page as the working calculation/review surface; Excel export should follow the accepted snapshot.
- For product-heavy origin views, use sheet tabs instead of stacking every product table on one long page.
- Missing unit prices are data-quality warnings, not a reason to hide an otherwise calculable temporary LVC percentage.
- Missing BOM/NVL is different from missing price and should still block LVC calculation.
- Keep phase-one multi-lot allocation snapshot-only in CO. Global reservation/trừ tồn across dossiers needs a ledger decision before implementation.
- Do not add new Data Hub endpoints from CO for allocation without the project’s Data Hub API request/approval flow.

## What Didn't Work
- The first LVC fix interpreted missing unit price as a hard block and blanked the percentage. User clarified that the percentage should still show as temporary; the logic was changed to partial statuses with warning UI.
- The first header fix targeted only the top navigation. User clarified the dark-theme bleed was still visible while scrolling; root cause was the sticky table header using translucent dark `surface-subtle`.
- Browser smoke used a temporary auth-disabled server on port `8002`; the normal server on port `8001` redirected unauthenticated requests to login as expected.
- Playwright was not installed locally, so final UI verification used HTML/CSS smoke checks rather than browser screenshots.

## Open Items
- Implement multi-lot C/O stock allocation:
  - allocation helper
  - case-level allocation pool
  - `allocation_lines` snapshot schema
  - UI source-line detail
  - hidden form round-trip
  - XLSX allocation trace export
- Decide allocation ordering: FIFO/source order, declaration date, lowest value, largest remaining quantity, or manual selection.
- Decide whether one NVL with many stock sources should stay one main row with expandable details in web, while Excel output may duplicate source trace rows.
- Decide whether saved dossiers reserve stock globally. If yes, design a ledger and likely request a Data Hub contract first.
- Define mixed-currency VNM behavior before summing multi-lot values across currencies.
- Keep unrelated `docs/co-form-index-confirmation.*` changes separate unless the user explicitly asks to include them.
