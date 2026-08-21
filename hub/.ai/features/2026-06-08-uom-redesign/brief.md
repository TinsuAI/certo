# UoM pages redesign — global standards + per-client factors

**Date:** 2026-06-08 · **Status:** built + verified locally (not committed)

## Why

Both UoM admin surfaces had bad UX:

- **Global `/admin/uom`** — canonicals and aliases lived in two *disconnected*
  flat tables. You couldn't see which aliases belonged to a unit, nothing was
  grouped, `base_factor` was a bare number with no human readout, add forms
  were buried in `<details>`, and there was **no way to edit or delete** a
  canonical (add-only).
- **Per-client `/clients/{id}/uom-factors`** — johnson-vn renders **537 rows**,
  each one a *simultaneous inline `<form>`* with emoji buttons (💾 ⌫). No
  search, no filter, cross-family rows (the ones that *require* a factor) mixed
  in with everything. The page wasn't even in the client nav — only reachable
  by deep-link from the catalog UoM panel.

## What changed

### Global standards (`admin/uom.html`)
- **Grouped by family** (conversion only happens within a family — that's the
  mental model). Each family is a header row: scaled families (mass/length/
  area/volume) read `đo lường · quy đổi qua gốc <base>`; count-like families
  (count/count_packaging/assembly) read `đơn vị đếm rời · coi như 1:1 · không
  quy đổi số học`.
- One **`Quy đổi về đơn vị gốc`** column with self-explanatory direction:
  `1 cm = 0.01 m`, `1 km = 1000 m`; base unit shows `đơn vị gốc (×1)` + a
  `gốc` badge; count units show `— (đếm)` (no fake `×1` noise).
- A **legend** explains canonical / alias / quy đổi, plus a cross-ref to the
  per-client factors page.
- Live **search** (code · family · alias; hides empty family headers).
- **Expand a row** → inline editor: change family + base_factor (labelled
  `1 đv này = ? gốc`), **delete the canonical** (aliases cascade), see/remove
  alias chips, add a new alias.

> v1 used a single flat searchable table with a redundant `×factor` column.
> Reworked to family grouping after feedback that the flat table was
> unintuitive (13 `count_packaging` units all showed `×1 / base`, looking like
> 13 base units) and the factor direction was unclear.

### Per-client factors (`clients/uom_factors.html`)
- Single **polished sortable table**, read-first. Sortable headers
  (Mã / Từ→Sang / Hệ số / Khác họ / Nguồn).
- **Search** + **"Chỉ khác họ"** filter; live count.
- Cross-family rows carry an amber left-accent stripe.
- **One shared inline editor** moved into the active row on "Sửa" — replaces
  the 537 simultaneous forms. Save / Hủy / Xóa.
- **Add panel** with a **live conversion preview** (`1 EA = 0.5 KG`); keeps the
  preview-prefill deep-link behaviour. Import moved into a collapsed `<details>`.
- Added the page to the **client nav** ("Cấu hình → Hệ số UoM").
- **Factor-direction annotation**: an info bar (`Hệ số là số NHÂN theo chiều
  từ → sang: SL(sang) = SL(từ) × hệ số`), a header tooltip, and a live
  `→ 1 ROLL = 1 PIECES` readout in the edit drawer (confirmed against
  `app/flatten/uom.py:62` → `q * match.factor`).
- **Cross-link** to the system-wide standards (`/admin/uom`, admin-gated).
- **Client-side pagination** (50/page, selector 25/50/100/all): johnson-vn has
  537 rows — too long to scroll. Search / cross-family filter / column sort run
  over the *full* set, then the matching+sorted rows are windowed to the current
  page (`1–50 / 537 · trang 1/11`, prev/next). Kept client-side on purpose:
  server paging would only search the current page and would lose page position
  on every edit/add/delete POST-redirect.

## Backend (scope: reskin + edit/delete canonical)
- `uom_standards.format_factor()` — clean factor display (no trailing zeros).
- `uom_standards.update_canonical()` / `delete_canonical()`.
- Routes `POST /admin/uom/canonical/{code}/update|delete`.
- `uom_view` enriches context (aliases grouped under canonical, family base
  unit, formatted factors). Client route adds `factor_disp` per row.

No schema change, no migration. `uom_aliases → uom_canonical` is
`ON DELETE CASCADE`, so deleting a canonical removes its aliases; override rows
reference UoM codes as free text and are untouched (code reverts to an unknown
alias until re-added).

## Verification
- `pytest -q` → **1431 passed, 16 skipped** (+5 new tests in `test_admin_uom.py`).
- UI smoke (`ui_smoke.py`) → screenshots in `screenshots/` (global collapsed /
  expanded / search; client list / editor / add-panel).

## Files
- `app/templates/admin/uom.html` (rewrite)
- `app/templates/clients/uom_factors.html` (rewrite)
- `app/templates/_client_nav.html` (+ nav link)
- `app/static/css/app.css` (+ UoM admin styles)
- `app/routes/master_data.py` (+ update/delete routes, enriched context)
- `app/routes/client_uom_factors.py` (+ factor_disp)
- `app/stores/uom_standards.py` (+ format_factor / update_canonical / delete_canonical)
- `tests/test_admin_uom.py` (+5 tests)
</content>
