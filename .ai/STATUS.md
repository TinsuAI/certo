# Project Status

## Current State
- **`main` = `origin/main` = prod = nightly = v0.15.0** (bumped from 0.14.0 — features below;
  git_sha = latest `main` commit, xem `barry-co.tinsu.ai/version` + `demo-co.tinsu.ai/version`).
  CI/CD green, tree clean. Features đầu session merged qua PR #3 (`834e1da`); version bump + changelog
  + handoff là commit cuối.
- **This session shipped 3 origin-flow features + 1 gate** (all live on `834e1da`):
  1. **Missing-price guard** — a non-originating NVL with no đơn giá understates VNM → LVC bị thổi
     (~100%). `/calculate` now parks such a sheet at `bom_loaded` (không chốt/xuất được), mirror của
     guard BOM rỗng (#13c). Shortage (có giá, thiếu tồn) vẫn chốt được → Mục 6 nguyên vẹn.
     Signal: `enrich_origin_product` sets `product["lvc_missing_price"]` (chỉ NVL `non_origin` thiếu giá).
  2. **Favourite ★ BOM mặc định (explicit-only)** — nút ★ trên picker mỗi SP để ghim/bỏ ghim version
     mặc định cho mã TP của khách (`POST /clients/{id}/bom-default`); badge + tooltip + đánh dấu version
     mặc định trong dropdown. **Đã BỎ auto-pin ngầm** (#14): chọn version giờ chỉ áp cho hồ sơ này.
     Read-precedence (hồ sơ mới tự dùng default) giữ nguyên. ★ chỉ hiện khi sheet THỰC SỰ có BOM.
  3. **Wizard "Xử lý tuần tự"** — nút toolbar mở luồng dẫn dắt: tính → DỪNG cho duyệt → chốt, lần lượt
     từng sheet theo thứ tự (bắt buộc tuần tự: calc N cần N-1 đã chốt). Mỗi bước mở thẳng sheet detail
     (bảng kê + LVC cập nhật real-time); thanh wizard NỔI (fixed, z-index 60) hiển thị ở cả dashboard
     lẫn sheet view. Sheet bị chặn (thiếu BOM/đơn giá) hiện lý do + "mở để sửa", không cho chốt. Không
     có nút "bỏ qua" (sẽ phá thứ tự). Orchestrate client-side trên `/calculate` + `/lock` sẵn có.
  4. **Tạm DISABLE 2 nút bulk cũ** "Chạy tồn (tất cả SP)" + "Chốt tất cả" (tooltip "đang xây dựng" →
     dẫn sang wizard). Routes `preview-stock-all`/`bulk-lock` còn nguyên, chỉ ẩn cửa vào UI.
- **DATA NOT PURGED.** prod `co-db-1` có cases thật (johnson-vn) + Growatt cost-allocation. **Do NOT
  seed/test against prod; dùng nightly HOẶC local dev DB.**
- Cost-allocation, Mục 6 (run-stock/substitute/bulk-lock routes), empty/no-BOM guard (#13c) — vẫn nguyên.

## Recent Changes (this session — live on `834e1da`, PR #3)
- `0e7128a` fix: block lock/export of sheets missing NVL đơn giá (+`lvc_missing_price` flag, +tests).
- `cea4292` feat: explicit favourite ★ BOM default (`POST /clients/{id}/bom-default`, context `bom_defaults`).
- `6f68610` feat: guided wizard "Xử lý tuần tự".
- `12d6e07` refactor: BOM default explicit-only (remove implicit write-through) + fix ★ on no-BOM sheet.
- `c2a99b6` fix: wizard opens sheet detail each step + floating bar (z-index 60, above sheet-view overlay).
- `834e1da` chore: temporarily disable bulk "Chạy tồn"/"Chốt tất cả" buttons.
- Tests: full suite **673 pass**; new `test_missing_price_lock_guard.py`, `test_bom_default_star.py`;
  updated `test_bom_default_store.py` (removed write-through tests → +no-auto-pin test), `test_co_demo.py`
  (2 demo export tests now price the 2nd NVL).

## Next Steps (priority order)
1. **Phase 2 of the bulk/wizard rework** (the disabled buttons are placeholders):
   - **Wizard: hiện "BOM: #N (mặc định)" trước khi Tính** — hiện wizard tính bằng version đang chọn
     (picker → ★ default → latest) ÂM THẦM; nên cho user thấy/đổi version trước khi tính.
   - Rebuild/re-enable a coherent batch flow OR retire "Chạy tồn"/"Chốt tất cả" hẳn (chúng đang disabled).
     Lưu ý "Thay định mức loạt" (bulk-substitute) hiện vào từ panel "Chạy tồn" → đang bị khoá theo.
   - Pre-flight summary cho bất kỳ batch-lock nào (sẽ chốt/bỏ qua sheet nào + lý do) trước khi commit tồn.
2. **Correctness/UX findings từ walkthrough đầu session** (xem `.ai/screenshots/2026-06-19-co-flow-walkthrough/FINDINGS.md`):
   ranking mã thay thế chôn mã điểm cao nhất (≙ client feedback **#4**, DH-side); modal thay-thế-loạt ẩn
   ΔLVC/ΔTrị giá (by design — no baseline).
3. **Client feedback 2026-06-05 còn lại:** **#12** số tồn TỔNG (aggregate SUM); **#4** ranking (DH-side,
   cần `.ai/api-requests/`).
4. `compact` PDF profile toggle; **EX1** column-K ref; **XX1** NVL có xuất xứ cột M-N. Backlog: B6/DC3/LK1/D1.

## Notes for Next AI Session
- **Sequential pipeline (quan trọng):** origin sheets xử lý **tuần tự + xen kẽ** — `/calculate` sheet N
  đòi N-1 đã **locked** (shared-stock correctness). Nên KHÔNG thể "tính hết rồi chốt hết"; wizard xen kẽ
  tính→chốt là đúng thiết kế. "Chốt tất cả" cũ chỉ chốt được sheet đang `calculated` → tên đánh lừa.
- **★ chỉ render khi có DH BOM:** picker version chỉ populate từ DH BOM artifacts. **Local dev env không có**
  cho hầu hết SP → ★ không hiện trên seed thường. Ngoại lệ: **`growatt-vn` PV00.0048500 CÓ** DH BOM #3
  (~300 NVL) → dùng nó để screenshot/verify ★ + wizard local. (Trái với note cũ "growatt-vn 0 versions".)
- **Local dev = auth-off + DB-mode** (`.env`: `CO_AUTH_REQUIRED=0`, `BARRY_DATABASE_URL`→`barry_co`,
  `DATA_HUB_ENABLED=1`→DH `:8754`). `npm run co:serve` = `:8001` (--reload watches app/ *.py/*.html/*.css).
- **Scratch e2e harnesses (gitignored)** ở `.ai/screenshots/2026-06-19-co-flow-walkthrough/`:
  - `e2e_lifecycle.py` — lock→reopen(gỡ tồn)→re-lock ledger + overclaim + empty-BOM + missing-price guard (SC1-7).
  - `wizard_e2e.{py,cjs}` — full wizard 2-sheet calc→review→lock (cả 2 `locked` trong DB).
  - `star_e2e`/`ui_walkthrough`/`e2e_lifecycle` — chạy với `.env` sourced + `NODE_PATH=$(pwd)/node_modules`.
  - Reusable DB-mode harnesses ở `.ai/scripts/` (bulk_lock_ledger, bom_default_incontainer, substitute_export).
- **Verify after merge:** `curl …/version` git_sha (prod=barry-co, nightly=demo-co). **NEVER** ghi literal
  CI-skip token trong commit msg → skip cả pipeline → prod không deploy ([[ci-skip-token-in-commit-msg]]).
- **Test env:** full file-mode (NO `.env`) = **673 pass**. DB/in-container e2e cần `.env`.
- PR convention (rule của user): commit/PR English, **không** trailer/co-author AI.
