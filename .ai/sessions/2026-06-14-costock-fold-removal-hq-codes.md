# Session: gỡ legacy CO-stock fold + bảng kê dùng mã HQ + CS1 modal

**Date:** 2026-06-14 · **Branch:** `refactor/co-stock-remove-legacy-fold` → merged PR #2 → `main` `a295a7d` → deployed.

## What Was Done

Bắt đầu từ "xem backlog có gì quan trọng", chốt model tồn CO, rồi thực thi 3 việc lớn — đã merge + deploy + verify live.

**1. Gỡ legacy CO-stock fold (CS2 decouple) — `ca11c37`.**
- Xoá `app/co_stock_adjustments_store.py`, `scripts/fix_trului_unit.py`, `tests/test_co_stock_fold.py`.
- Gỡ `fold_baseline` / `apply_adjustments` / `aggregate_by_lookup_key` / `refold_adjustment_lots` / `refold_all_adjustments` + mọi call fold (materializer `:106`, `co_case_context` source-context overlay, export route). Param `fold` của materializer bỏ.
- Route `/co-stock/import` overlay xoá; form "Import tồn CO" (co_stock.html) repoint → `/co-stock/import-snapshot`.
- **Migration 017** `drop table co_stock_adjustments` (đã apply dev + prod via deploy).
- Model: `tồn = opening (DH BCCT) − baseline_used (workbook chốt off-app, bake thẳng) − live claims`; read-time `co_stock_ledger.apply_used_qty`. DH refresh = opening-only (baseline 0).
- **CS1:** `fold_lot_events` (co_stock_events_store) gộp mọi `snapshot_row_*` thành 1 dòng "Hệ thống · nguồn" (đếm thêm/cập-nhật/gỡ + cờ `readded`), ghim cuối, mờ bằng color token; template + CSS + 14 test. Screenshots `.ai/screenshots/2026-06-14-cs1-lot-history-modal/`.

**2. Bảng kê dùng mã HQ — `ffeeac0` + `8f9f166`.**
- Vấn đề: Growatt lookup/match bằng `allocation_code` nội bộ (dotted 012.x) nhưng export phải ra **mã HQ** = `customs_item_code` của lô khớp (category DAYTINHIEU/LKN-VAN…). 88% lô growatt có HQ ≠ nội bộ.
- `co_case_context` material builder: gom `customs_item_code` từ `allocation_lines` → `customs_material_code`.
- Display (co_case.html): "Mã NVL" = HQ chính + "nội bộ: …" phụ. `material_code` nội bộ vẫn cho `decl_mat_key`/substitute.
- Export: **bang_ke_renderer.py `render_into_sheet`** (đường ACTIVE, config-driven LVC/RVC…) ghi mã HQ; `workbook_io.write_hq_sheet_materials` (fallback legacy) cũng sửa. Test cho cả hai.

**3. Docs/memory:** STATUS/BACKLOG/brief + memories cập nhật (fold removed, CS3 model, HQ codes, 2-render-paths).

**Verify (live, data thật):**
- File-mode suite **593 pass**; DB-backed origin/recalc/lock/close-gate/soft-delete **pass**.
- Gỡ fold: route legacy → 404, bảng dropped, lot-history → 200.
- e44 (reopen → Load BOM → Tính → Chốt qua Playwright): 0 không-tồn, 0 vượt-tồn, **LVC 49.92%** (tự verify khớp render). 162 claim, 0 over-claim.
- **File export thật** (`GET /export-bang-ke`): cột Mã = DAYTINHIEU + 93 HQ-category, **0 mã nội bộ**, 122/122 NVL có customs.
- Merge PR #2 → deploy run `27508328877` success; prod `/version` git_sha `a295a7d`.

## Decisions Made
- **Model tồn CO (user chốt):** 3 nguồn sở hữu 3 đại lượng — DH=opening (feed BCCT read-only), workbook import=chốt baseline off-app @T (ghi remaining THẲNG, KHÔNG trừ), CO=tiêu hao. Tồn CO sống 100% ở app CO, DH không giữ tồn.
- **Gỡ fold KHÔNG cần parity-migration** vì prod = data test (user xác nhận disposable). Nếu prod thật → phải parity test trước.
- **Bảng kê = mã HQ; allocation = lookup-only** (user chỉ đạo). Mã HQ lấy từ lô khớp (per-lot, không lookup global vì allocation→HQ ~1:1 nhưng có 12% lệch).
- **CS3 full-harmonize (DH+workbook coexist) = PARK** — chưa client nào cần; guard `is_workbook_sourced` hiện chặn DH cho client workbook = conservative-safe.

## What Didn't Work
- **Fix mã HQ lần 1 (`ffeeac0`) chỉ sửa `write_hq_sheet_materials`** — đó là FALLBACK legacy. File export thật vẫn ra mã nội bộ. Unit test pass = tin tưởng GIẢ. Đường thật là `render_into_sheet` (config-driven). Sửa ở `8f9f166`. → **Bài học: verify trên artifact thật, không chỉ unit test.**
- **2 fix `opening_qty` (apply_used_qty + derivation)** lúc nghi recalc break — đuổi bug ẢO (122 không-tồn là artifact của e2e force-click khi BOM chưa nạp xong). Đã revert.
- **Source `.env` rồi chạy full suite** → 52 fail giả ([[test-env-filemode-vs-datahub]]). Chạy lại file-mode sạch = 593 pass.
- **Reopen/recalc qua curl** → 409 (thiếu form revision token). Phải qua Playwright (form submit thật).
- **Tự recalc để verify HQ** bị chặn lâu: case dev đều locked-có-NVL hoặc rỗng-NVL (cruft, `product.code`=None); tạo mới cần TKX. Cuối cùng reopen e44 qua Playwright OK.

## Open Items
- CS3 full-harmonize + XX1 + LK1 + B6/B7 + D1 (parity test) — xem STATUS Next Steps.
- Branch `refactor/co-stock-remove-legacy-fold` đã merge — có thể xoá (local + origin).
- Dev server `:8001` (task b0bzczccq) — kiểm còn sống.
- e44 đã re-Chốt với mã HQ (clean). johnson-vn co_stock_rows còn baseline cũ tới lần refresh kế (test data).
