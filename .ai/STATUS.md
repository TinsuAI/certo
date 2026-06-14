# Project Status

## Current State
- **On `main` = `origin/main` = `d80863e`**. **DEPLOYED to prod.**
  prod `barry-co.tinsu.ai/version` = `0.14.0` / git_sha `d80863e` / build 2026-06-14T19:46 / source `build`.
  CI/CD run `27510005484` success (prod + demo + nightly). Tree clean.
- **2026-06-15 session:**
  1. **VERIFIED Growatt data CO-ready** — stock 38287 lô (all remaining>0), config `description_regex` v2
     refresh hôm nay; BOM↔tồn match **99%** (e44 100%/LVC 49.92% locked). **Re-calc proof:** stale case
     94feac BIENTAN.17 `0%→99.6%`, LVC `100%(ảo)→19.67% partial_fail`. Landmine: stale calc giấu LVC-fail sau
     pass 100% giả. [[growatt-allocation-strategy-bom-match]].
  2. **FULL PURGE cases + claims (dev + prod, mọi client)** — user reset stale test data. dev 170 cases/949
     claims→0, prod 7/1215→0; **stock GIỮ** (dev 98462, prod 104232). Backup `data/local/backups/full-purge-20260615-032608/`(+`/prod`).
  3. **Code fix `d80863e` (committed + DEPLOYED):** `co_case_store.load_state` — gỡ json re-seed; DB mode KHÔNG
     còn đọc/reseed `cases.json` (chống zombie cases). json chỉ còn dùng ở file-mode (test). Dev `cases.json` xoá hẳn.
     File-mode suite **594 pass**. [[co-case-store-db-json-reseed]].
- **SHIPPED this session (3 things, all live on the test-data prod):**
  1. **Gỡ legacy CO-stock fold** — `fold_baseline`/`co_stock_adjustments`/`refold_*` xoá hẳn; bảng
     `co_stock_adjustments` dropped (**mig 017**); route `/co-stock/import` overlay bỏ (form → `/import-snapshot`).
     Tồn = `opening (DH BCCT) − baseline_used (workbook chốt off-app) − live claims`, read-time `apply_used_qty`.
  2. **Bảng kê dùng mã HQ** — display + export dùng `customs_item_code` (mã HQ) thay `allocation_code` nội bộ.
  3. **CS1** — redesign modal lịch sử lot (gộp sự kiện hệ thống + cờ `readded`).
- **Dev server:** background task `b0bzczccq` on `:8001` (`npm run co:serve`, --reload). Sau khi checkout về
  `main` nó serve `a295a7d`. Kiểm còn sống / restart nếu cần.
- **Mid-flight: nothing.** Code fix committed + deployed (`d80863e`); data purge dev+prod done + verified live (prod cases 0, stock 104232 intact). Demo/nightly NOT purged (separate stacks, still have old cases).

## Recent Changes (this session, latest first)
- **`a295a7d`** Merge PR #2 `refactor/co-stock-remove-legacy-fold` → main.
- **`8f9f166`** fix(co-case): config-driven renderer (`bang_ke_renderer.render_into_sheet`, **đường export
  ACTIVE** cho form có config) cũng dùng mã HQ. **Bắt được nhờ verify trên FILE export thật** — unit test trên
  `write_hq_sheet_materials` (fallback legacy) cho tin tưởng GIẢ. Memory [[bangke-export-two-render-paths]].
- **`ffeeac0`** fix(co-case): bảng kê dùng mã HQ (material builder kéo `customs_item_code` lô khớp + display
  HQ chính/nội bộ phụ + legacy writer + test).
- **`ca11c37`** refactor(co-stock): gỡ legacy fold (xoá `co_stock_adjustments_store.py`, `fix_trului_unit.py`,
  `test_co_stock_fold.py`; mig 017) + CS1 modal redesign.
- **`793007b`** docs(backlog): stale-status reconcile (BG1/RD1/RD2 done, RD3 partial).

## Next Steps (priority order)
1. **CS3 full-harmonize — PARKED** (model locked, brief `.ai/features/2026-06-14-cs3-costock-three-sources/`):
   nới `is_workbook_sourced` để DH thêm opening **lô mới** trên client đã chốt workbook + rule re-import
   reconcile. Làm khi có client thật cần cả 2 nguồn. [[cs3-costock-harmonize-model]].
2. **XX1** — NVL CÓ xuất xứ (phụ lục X) → nhánh có-xuất-xứ (ảnh hưởng LVC/RVC); đụng field origin per-lot của
   DH. `/discover`.
3. **LK1** — review Chốt lock-able (chốt khi dirty / còn `declarable_unmatched` → chặn cứng?).
4. **B6** (nguyên tệ luôn ra VND) · **B7** (dropdown "chỉ tiêu" nền đen) — user-reported UX.
5. **D1** — delta-vs-full refresh parity (chưa có parity test). CS1 phát hiện vân tay churn: lô có
   `snapshot_row_added` (mới) + `updated` (cũ) mà KHÔNG có `removed` = wipe snapshot âm thầm.
6. **growatt-vn prod re-calc — DEFERRED** (prod = test data; re-derive ở lần ingest thật kế).
   [[prod-test-data-recalc-deferred]].
7. M1 (propose-BOM status sync), DC1/DC2/DC3 (declarability), P1 residual (index N+1), T1 (test-DB isolation).

## Notes for Next AI Session
- **Test env (bit me this session):** file-mode (NO `.env`) `PYTHONPATH=. uv run python -m pytest` = **593 pass**.
  ĐỪNG source `.env` rồi chạy full suite trong cùng shell → ~52 fail GIẢ (test_co_demo/data_hub). DB-backed
  co_stock/origin tests CẦN `.env` — chạy riêng. [[test-env-filemode-vs-datahub]].
- **Bảng kê có 2 đường render export** [[bangke-export-two-render-paths]]: config-driven `render_into_sheet`
  (`bang_ke_renderer.py`, ACTIVE) vs `write_hq_sheet_materials` (`workbook_io.py`, fallback). Sửa **cả 2** +
  verify trên FILE thật (`GET /co-case/{id}/export-bang-ke` → cột Mã = col C, row 16). Đừng tin unit test trên
  nhánh sai.
- **Mã HQ vs nội bộ (Growatt):** bảng kê = `customs_item_code` (HQ: DAYTINHIEU/LKN-VAN…); `allocation_code`
  (dotted 012.x) CHỈ tra cứu/khớp. 88% lô lệch. Material builder kéo HQ từ lô khớp ở `co_case_context`.
- **Model tồn CO giờ:** opening − baseline_used (workbook chốt) − live claims; KHÔNG fold; bảng
  `co_stock_adjustments` đã drop. [[co-stock-folded-remaining-model]] + [[cs3-costock-harmonize-model]] đã cập nhật.
- **Verify recipe:** reopen sheet phải qua Playwright (curl 409 — thiếu form revision token). e44
  (`growatt-vn/co-case-e44fe2065b62`, sheet `SD00.0010600`) đã re-Chốt với mã HQ; verified 0 không-tồn, 0
  vượt-tồn, LVC 49.92%, export cột Mã = HQ.
- **Deploy:** merge/push `origin main` (TinsuAI/co) → runner auto-deploy prod+demo+nightly ~1-2min;
  `[skip ci]` HEAD skip. [[deploy-remote-tinsu-co]].
- **Local `main` đã sync `origin/main` (a295a7d).** Branch `refactor/co-stock-remove-legacy-fold` còn (merged) —
  xoá được. Có remote `tinsu` cũ (local ahead) — bỏ qua, deploy đi qua `origin`/TinsuAI.
