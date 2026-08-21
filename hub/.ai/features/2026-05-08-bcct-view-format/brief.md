# BCCT view — number format, currency-correct labels, column picker

**Date:** 2026-05-08
**Branch:** main (direct, single-feature)
**Owner:** dennis
**Status:** Implemented

## Why

User feedback during pre-MVP review of BCCT list view at `/clients/<id>/bcct`:

1. **Numbers unreadable.** `quantity` and `total_value` rendered via
   `'%.2f'|format(...)` — no thousand separators. A 12-billion-VND value
   shown as `12480972000.00` is hard to scan.
2. **Currency mislabeled.** The single value column showed `total_value`
   (VND-domain after mig 039) next to a label sourced from `currency_nt`
   (FX-domain). Result: a Growatt export of 478,800 USD displayed as
   "12,480,972,000 USD" — clearly VND magnitude, wrong currency.
3. **No column control.** Staff want to hide rarely-used columns
   (declaration_type, line_no, unit) without DB edits or template forks.

Mig 039 already split FX and VND domains at the data layer; the view
hadn't caught up.

## What changed

### Macros (new shared partials)

- `app/templates/_format.html` — `format_number`, `format_money`,
  `format_date`, `format_int`. Locale-aware via `lang` arg
  (`vi` → `1.234.567,89`; default `en` → `1,234,567.89`). Handles
  `None`/empty input.
- `app/templates/_sort.html` — extracted `sort_th(col, label, sort,
  sort_link, attrs)` macro previously duplicated in bcct/bqd/catalog/bom
  templates. BCCT migrated; others untouched in this PR.

### BCCT list (`app/templates/clients/bcct.html`)

- "Giá trị" + "NT" two-cell pair → "Giá trị NT" + "Giá trị VND" two
  data-correct cells. NT cell renders `total_value_nt` next to
  `currency_nt`; VND cell renders `total_value` next to literal `VND`.
- `format_number` applied to `quantity` (2 dec) and money (NT 2 dec,
  VND 0 dec). `format_date` applied to `registration_date`.
- `<th>`/`<td>` pairs gained `data-col="<key>"` attributes matching a
  Python-side column registry (`bcct_columns` in template).

### Column picker

- `app/static/js/col-picker.js` — vanilla module, ~80 lines. Reads
  `localStorage` key `colpicker:<view_key>` (JSON array of *hidden*
  column keys; missing key = visible). Wires every
  `<details class="col-picker" data-view-key="X">` against the
  `<table data-col-table="X">` sharing the view key.
- Inline `<details>` panel above the BCCT table with checkboxes per
  column + "Mặc định" reset button. Default-visible state lives in the
  Jinja column registry, not JS — so adding a column flips on for
  everyone unless they've explicitly hidden it.

## Why we did NOT build a generic "view engine"

User asked whether to build a Notion/Odoo-style engine. Critic agent +
my own re-analysis flagged the catalog template (~30-line composite
"Quan sát" cell + inline-edit "Nguồn cung BTP" cell) as proof the widget
abstraction would leak by view #2. Decision: **macros over registry**.
Each view keeps its own `<th>`/`<td>` structure; only the truly shared
helpers (format, sort_th, picker JS) get factored. Re-evaluate if and
when 3 templates copy-paste the same widget logic.

See conversation transcript or DECISIONS.md if added.

## Manual test plan

1. Login `admin@data-hub.local`, go to `/clients/growatt-vn/bcct?direction=export`.
   - Verify a row shows "478.800,00 USD" in NT col and "12.480.972.000 VND"
     in VND col (vi-VN format).
   - Verify dates render `2026-05-08` (no time-of-day).
   - Verify quantity uses thousand separators (`420` or `1.140` etc).
2. Click "⚙ Hiển thị cột" → check/uncheck checkboxes → cells hide/show
   in real time.
3. Reload page — hidden columns stay hidden (localStorage round-trip).
4. Click "Mặc định" — all columns visible again.
5. Switch language en/vi (top-right toggle) — number format follows.

Captured screenshots in `screenshots/`:
- `01_bcct_export_currency_pair.png` — default view, USD + VND both
  rendered with correct labels.
- `02_bcct_column_picker_open.png` — picker panel expanded.
- `03_bcct_columns_hidden_persisted.png` — Dòng/Loại/ĐVT hidden,
  persisted across reload.
- `04_bcct_import_currency_pair.png` — import direction, mixed VND/USD
  rows.

## Done criteria

- [x] BCCT export view shows correct currency next to each amount
  (USD-amount cell labeled USD; VND-amount cell labeled VND).
- [x] Numbers use locale-aware thousand separators (vi-VN by default).
- [x] Dates render `YYYY-MM-DD`.
- [x] Column picker hides/shows cells in real-time, persists in
  localStorage.
- [x] No DB schema change (mig 035-041 already provided FX/VND split;
  this PR only updates the view).
- [x] Tests for format macros (12 tests pass; pinned format strings).
- [x] Existing BCCT tests still pass.

## Out of scope (explicit deferrals)

- **Other views** (Catalog, BQD, Uploads, Proposals, BOM artifacts,
  Parser-rules) — keep current rendering until they actually need
  format/picker work. Macros are available; opt-in per view.
- **Per-row inspect view** (`/clients/<id>/bcct/history/.../...`) —
  has 40 typed columns; format helpers should apply but isn't in this
  PR (separate touch-up).
- **Upload preview** (`bcct_upload_preview.html`) — same.
- **Server-side user prefs (DB-backed)** — localStorage is enough for
  pre-MVP single-device usage. Promote to DB if/when cross-device
  becomes a real ask.
- **Abbreviated number format (12.5B)** — user wanted thousand-separator
  only; abbreviated mode considered then dropped (loses precision for
  customs use case).

## Files touched

```
A app/templates/_format.html
A app/templates/_sort.html
A app/static/js/col-picker.js
M app/templates/clients/bcct.html
A tests/test_format_macros.py
A .ai/features/2026-05-08-bcct-view-format/brief.md
A .ai/features/2026-05-08-bcct-view-format/ui_smoke.py
A .ai/features/2026-05-08-bcct-view-format/screenshots/*.png
```
