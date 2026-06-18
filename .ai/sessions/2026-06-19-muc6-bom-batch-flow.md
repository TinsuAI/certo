# Session 2026-06-18→19 — Mục 6: BOM default + batch run-stock / substitute / lock

Continued the 2026-06-18 client-feedback work into **Mục 6** (the BOM batch workflow = #13 + #14
from the 2026-06-05 `HIỆN TRẠNG BARRY CO` feedback). Discovered → built in 4 slices → e2e-verified →
shipped to prod + nightly (`1313ba0`). 7 commits on branch `feat/bom-default-pick`, ff-merged to main.

## What Was Done
Feature brief: `.ai/features/2026-06-18-bom-default-batch-flow.md` (after `/discover` with 3 Explore agents).

- **Slice A (#14) — per-client default BOM pick** (`8f85e1f`): new `app/bom_default_store.py`
  (Postgres `co_bom_product_default` + JSON fallback, mirrors `cost_allocation_store`), migration
  `018_bom_product_default.sql`, write-through helper `persist_bom_picks_as_defaults` in the
  `/origin/save`+`/autosave` chokepoint `origin_case_from_request`, read-time fallback layer in
  `selected_bom_rows_by_product(case, ws, client_defaults=None)` (auto-reads from `case.client_id`).
- **Slice B (#13a) — run stock once** (`c9f5183`): `case_missing_stock_summary` +
  `case_stock_preview_summary` (co_case_context) + route `POST .../origin/preview-stock-all`
  (non-committing) + "Chạy tồn (tất cả SP)" toolbar button + summary panel.
- **Slice C (#13b) — bulk substitute** (`8195ff9`): `material_row_index`, route
  `POST .../origin/bulk-substitute` (override at matched row, skip-and-report, persist, re-preview),
  `whole_case_stock_summary` (override-aware: recomputes per sheet so re-preview reflects swaps).
  **UX redesign (per user feedback "sơ sài"):** the bulk panel reuses the SAME rich sheet substitute
  modal in **stage-mode** — added `state.bulkPick` branch in the modal `apply()`, a module-level
  `openBulkSubstitutePicker`, allowed short picks + suppressed Δ columns in bulk. Panel enriched with
  name/cần/có/thiếu + staged-pick display + result summary.
- **Slice D (#13c) — chốt tất cả** (`bd09a87`): route `POST .../origin/bulk-lock` mirroring the
  single `/lock` (validate → `record_sheet_lock_claims` → set locked → persist per sheet) +
  "Chốt tất cả" toolbar button (confirm → reload only when something newly locked).
- **e2e harnesses** (`198d70a`, `edc3b2d`, `1313ba0`): ledger claims, in-container BOM default,
  substitute→export correctness. **656 file-mode tests pass.**

## Verification (the "cẩn thận" e2e push)
- **Browser e2e with assertions + screenshots** (puppeteer, `.ai/screenshots/.../e2e_muc6.cjs/.py`,
  local auth-off DB-mode): B/C/D all PASS — run-stock lists shortages, modal shows ranked
  candidates + score + đủ/thiếu + per-lot table, stage, apply, lock; no JS errors (favicon-404 only).
- **Slice D ledger** (`e2e_bulk_lock_ledger.py`, real Postgres): claims written to `co_stock_claims`,
  overclaim rejected, cross-case `used_qty`, idempotent. PASS.
- **Slice A** (`e2e_bom_default_incontainer.py`, **nightly deployed image** via ssh/docker exec):
  write-through to `co_bom_product_default` + diff-guard + precedence reuse. PASS.
- **Correctness** (`e2e_substitute_export.py`): a sheet calculated against a real lot exports that
  code; after `bulk-substitute` swap, re-export shows the SUBSTITUTE code (allocated against its
  stock), original gone, consumed qty preserved — parsed from the real xlsx via openpyxl. PASS.

## Decisions Made
- **Reuse the sheet's substitute modal for bulk** (not a parallel UI): least risk, identical UX. Hooked
  via a `bulkPick` stage callback so the sheet flow is untouched when unset.
- **Preview is override-aware via per-sheet recompute** (`recalculate_origin_sheet_edits` /
  `prepare_case_origin_sheet` chained in order) — correct sequential consumption + reflects swaps.
- **bulk-lock persists per sheet** (not once at end) to avoid ghost-claims on mid-loop failure.
- **Pin the chosen BOM version** (not auto-latest) per user choice; write-through only on a CHANGED
  pick (diff vs the case's prior override) so editing an old case can't clobber a newer default.
- Shipped to prod (additive: migration `IF NOT EXISTS`, empty-default precedence = no behavior change
  for existing cases) after `/rev` on each slice.

## What Didn't Work
- **Slice A browser pick not stageable locally:** a hand-seeded case product shows "❗ Chưa có BOM" —
  the BOM picker `<select>` is only populated through the BCCT/invoice match flow. Verified Slice A
  server-side on the nightly image instead.
- **Δ columns in the bulk substitute modal showed nonsense** (-3431% LVC) because bulk mode has no
  original-material baseline → suppressed them in bulk (kept đủ/thiếu + lots + score).
- **Initial bulk-lock JS** reloaded even when nothing locked (lost the skip reasons) — fixed to reload
  only when something was newly locked.
- Local DB has no CO BOM workspace for `-vn` clients (only demo `growatt`/`johnson`) → two e2e flows.

## Open Items
- Client feedback still open: **#12** (số tồn tổng), **#4** (substitute ranking — DH-side via
  `.ai/api-requests/`). Plus compact-PDF UI toggle, EX1, XX1 — see STATUS Next Steps.
- The browser pick → autosave → default UI binding for Slice A is the one sliver not browser-verified
  (logic verified server-side). Could be closed with a properly-matched case on nightly.
- `feat/bom-default-pick` can be deleted (folded into main).
