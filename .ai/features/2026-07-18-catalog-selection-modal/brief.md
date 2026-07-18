# Catalog candidates — per-row selection + single-row accept modal (#55)

**Date:** 2026-07-18 · **Issue:** #55 · **Branch:** `feat/catalog-candidate-selection-modal`

## Problem

Two shapes that didn't fit how the page is used:

1. **No subset.** "The filter IS the rule" (#35): the bulk button approved the
   *whole* filtered set — you could not approve 5 codes and skip the 6th. The
   server deliberately re-applied the filter and ignored any client-sent code
   list (ADR-0001's "no rule-authoring DSL / no trusted client list").
2. **Inline form in a table cell.** The per-row «Duyệt» was a
   `<details><summary class="btn-primary">` expanding a 5-field form inside the
   cell — cramped and out of place.

## What shipped

### Per-row selection (two-tier, pagination-aware)

- A checkbox column; each row checkbox is `name="codes"` bound to the approve
  form via `form="bulk-form"` (so the table keeps its own reject forms without
  nesting).
- A header checkbox selects the visible page (indeterminate when partial).
- When the page is fully checked and there is more beyond it, a banner offers
  **"Chọn tất cả N mã khớp bộ lọc"**, which sets a hidden `select_all_matching`
  flag.
- The approve button tracks the selection: disabled at zero → "Duyệt N mã đã
  chọn" → "Duyệt toàn bộ N mã khớp bộ lọc".

### Server — intersection, not trust (ADR-0001 amendment)

`bulk_accept` now takes `codes[]` or `select_all_matching`. For an explicit
list it recomputes `_filter_pending(...)` and accepts only
`selected ∩ filtered-pending`. A code that is stale, already a material,
machinery, or outside the active filter is dropped; a code that was never
pending cannot be forced in via the POST. `select_all_matching=1` reproduces
the old whole-filter path. **The filter is still the outer bound** — it can only
shrink the writable set, never grow it.

Empty submit (no codes, no flag) is a no-op: selection is explicit now, not
"empty means all".

### Single-row accept modal

Row «Duyệt» is a `<button>` carrying the row's `data-*`; JS fills one shared
native `<dialog>` and `showModal()`s it. Posts to the **unchanged** `/accept`
route. `data-category` mirrors the bulk path's derivation (`suggested_category`,
else a flattened-BOM leaf → `nvl`) so the dropdown prefills correctly instead of
defaulting to the first option — a wrong-category footgun the old inline form
also had. A `<noscript>` link to the detail page keeps the flow usable without
JS.

## The security property, kept

> A code that was never pending cannot be approved by placing it in the POST.

`tests/test_catalog_candidate_selection.py` — 6 tests: selected-only,
injected-code-dropped, outside-filter-dropped, select-all-matching parity,
empty-is-noop, selection ∩ filter.

## Proof

`screenshots/` + `ui_smoke.py` drive the real page: button disabled → "3 mã đã
chọn" → full-page banner → "toàn bộ 111 mã khớp bộ lọc" with the flag set →
dialog opens prefilled. The smoke asserts each and exits non-zero on mismatch.

Run: `uv run python .ai/features/2026-07-18-catalog-selection-modal/ui_smoke.py`
(dev server up on :8754).

## Files

- `app/routes/catalog_discovery.py` — `bulk_accept` takes `codes` |
  `select_all_matching`, intersects.
- `app/templates/clients/catalog_candidates.html` — checkbox column, approve
  bar + banner, `<dialog>`, row button.
- `app/static/js/catalog-candidates.js` — new: selection + banner + dialog.
- `app/static/css/app.css` — checkbox column, dialog, `.form-stack`.
- `docs/adr/0001-*.md` — amendment recording the client-selection contract.

## Not in scope

The "Đề xuất" column's four meanings; the detail page's own inline accept form
(same `<details>` pattern, convert later if wanted). Reject stays a one-click
confirm.
