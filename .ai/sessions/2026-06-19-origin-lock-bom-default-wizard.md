# Session 2026-06-19 — origin lock/BOM-default hardening + guided wizard

Long session: started as a "play the user" CO-flow walkthrough + comprehensive test campaign,
turned into shipping 3 origin-flow features + a gate, all merged to `main` and deployed
(prod + nightly), v0.14.0 → **v0.15.0**.

## What Was Done

### 1. Comprehensive walkthrough + test campaign (no code change)
- Drove the real auth-off DB-mode dev server (`:8001`, client `growatt-vn`), verifying BOTH UI/UX and
  internal DB logic per scenario. Built `.ai/screenshots/2026-06-19-co-flow-walkthrough/e2e_lifecycle.py`
  (TestClient, real routes): SC1 lock writes `co_stock_claims` (qty/lot/status correct), SC2 overclaim
  rejected (409, no claim), SC3 reopen/gỡ-tồn SOFT-releases (`status='released'`, overlay drops), SC4
  re-lock, SC5 empty/no-BOM guard via real `/calculate`, SC6 shortage still lockable, SC7 missing-price.
- Reran `e2e_muc6.py` (happy path) + `e2e_substitute_export.py` (export reflects swap) — green.
- Findings written to `.ai/screenshots/2026-06-19-co-flow-walkthrough/FINDINGS.md`.

### 2. Missing-price guard (`0e7128a`)
- `enrich_origin_product` sets `lvc_missing_price` = any active **non_origin** material with missing
  đơn giá (`valuation_status==missing_unit_value` or `unit_value_missing`).
- `calculated_sheet_status` now returns `bom_loaded` (not `calculated`) for `lvc_missing_price` too →
  the sheet can't be locked/exported (mirrors the empty/no-BOM #13c guard). Shortage (priced, low stock)
  stays `calculated`/lockable. `/calculate` surfaces a "thiếu đơn giá" message. `+test_missing_price_lock_guard.py`.

### 3. Favourite ★ BOM default (`cea4292`, reworked in `12d6e07`)
- `POST /clients/{id}/bom-default` (set/clear), context exposes `bom_defaults`, ★ on each product's
  picker + "mặc định" badge + dropdown marking. `+test_bom_default_star.py`.
- **Reworked to explicit-only:** removed the implicit write-through (`persist_bom_picks_as_defaults`) —
  picking a version is now per-case only; ★ is the sole way to pin the client default. ★ only renders
  when the sheet actually has a BOM (fixed "★ Mặc định" appearing on a "Chưa có BOM" sheet — the bug
  the user caught). Read-precedence unchanged.

### 4. Guided wizard "Xử lý tuần tự" (`6f68610`, fixed in `c2a99b6`)
- Toolbar button → floating bar that steps each sheet calc → pause-for-review → lock, in order; opens
  the sheet DETAIL each step (bảng kê + LVC real-time); blocked sheets show the reason. No skip button.
- Client-side orchestration over existing `/calculate` + `/lock`; reads per-panel `data-*` after each
  shell swap. Bar moved to `origin-step-root` level, `position:fixed` z-index 60 (above the sheet-view
  full-screen workspace overlay) so it stays visible in both views.
- Verified by `wizard_e2e.{py,cjs}` — full 2-sheet calc→lock, both `locked` in DB.

### 5. Disabled old bulk buttons (`834e1da`)
- "Chạy tồn (tất cả SP)" + "Chốt tất cả" disabled with "đang xây dựng" tooltip → funnel to the wizard.
  Routes untouched, only UI entry points gated.

### 6. Release + handoff
- Bumped `pyproject.toml` 0.14.0 → **0.15.0**; CHANGELOG 0.15.0 entry (user-facing, VI).
- PR #3 opened + ff-merged to `main`; CI/CD green; prod + nightly verified at the merge sha.

## Decisions Made
- **Block missing-price, keep shortage lockable** (user call): missing đơn giá → LVC tạm tính → block;
  shortage keeps prices → Mục 6 intact. Scoped to `non_origin` only (origin NVL không vào VNM).
- **BOM default = explicit-only** (user call): the implicit auto-pin was the confusion ("không hiểu cái
  gì mặc định"). ★ is now a conscious pin; picker = per-case.
- **Wizard = guided, interleaved, pause-per-sheet** (user call), NOT a batch "tính hết rồi chốt hết" —
  because the pipeline is strictly sequential (calc N needs N-1 locked, shared-stock correctness).
- **Disable old bulk buttons** rather than rebuild now — Phase 2.

## What Didn't Work / Gotchas
- **`/calculate` is strictly sequential**: sheet N can't calculate until N-1 is **locked** (verified).
  So "Tính tất cả rồi Chốt tất cả" is impossible; "Chốt tất cả" only ever locked the one `calculated`
  sheet (misleading name). This drove the wizard design.
- **★ can't render on most local seeds**: the BOM version picker only populates from DH BOM artifacts,
  which local dev lacks for most products. **`growatt-vn` `PV00.0048500` HAS a DH BOM (#3, ~300 NVL)** —
  use it to verify ★/wizard locally. (Corrects the old "growatt-vn 0 versions" note.)
- A seeded `bom_loaded` sheet renders `lvc_status=missing_bom` (materials only resolve on `/calculate`);
  seed wizard cases as `draft` so the wizard's "Tính" path is exercised, not the "blocked" path.
- Floating fixed bar was hidden by the sheet-view `[data-origin-sheet-workspace]` overlay (z-index 50) —
  needed z-index 60. Puppeteer native `.click()` trips on the fixed bar; use in-page `el.click()`.

## Open Items (Phase 2)
- Wizard: show "BOM: #N (mặc định/đang chọn)" before Tính (currently uses the resolved version silently).
- Rebuild or retire the disabled "Chạy tồn"/"Chốt tất cả" (note: "Thay định mức loạt" was reachable only
  from the "Chạy tồn" panel → currently inaccessible). Add a pre-flight summary to any batch-lock.
- Walkthrough findings: substitute ranking buries the top-score candidate (≙ client #4, DH-side).
- Client feedback still open: #12 (số tồn TỔNG), #4 (ranking, DH-side `.ai/api-requests/`).
