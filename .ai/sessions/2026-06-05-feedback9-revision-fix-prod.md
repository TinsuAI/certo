# Session 2026-06-05 — Feedback #9 revision fix + prod deploy

## What Was Done
- Phân tích bảng phản hồi khách `HIỆN TRẠNG BARRY CO.pdf` (14 mục) → tạo
  `.ai/feedback/2026-06-05-hien-trang-barry-co.md` (trạng thái từng mục).
- **Fix #9** ("phải F5 mới load được BOM sheet tiếp"):
  - Đọc toast lỗi từ ảnh PDF (trích ảnh nhúng độ phân giải đầy đủ) = `"Origin case state
    changed; reload before saving."` → đây là 409 optimistic-revision (`co_case.py:159`),
    KHÔNG phải race.
  - Root cause: `origin_case_revision` hash `source/bom/origin_snapshot` — dữ liệu phái sinh
    `co_case_context` tính lại mỗi render (`attach_case_source_summary_snapshot` ~line 170 +
    attach_* line 184-200). `source_snapshot` chứa `bcct_reviewed_row_count`,
    `correction_candidate_count`, catalog version ids — biến động liên tục trên prod. Lock
    route persist ở 1547 nhưng rebuild snapshot khi render ở 1549 → revision render khác bản
    đã lưu → action kế (calc sheet2) 409.
  - Fix: `origin_case_revision` chỉ hash `origin_product_order` + per-sheet `status` +
    `bom_product_artifact_overrides`.
  - Test: `tests/test_origin_case_revision.py` (token ổn định khi snapshot drift, đổi khi
    user sửa). Full `test_co_demo.py` + policy = 190 passed, 6 skipped.
- **Deploy prod:** sửa `origin` remote → `TinsuAI/co`, push `9bb855c` (fast-forward từ
  8a07466) → CI runner `tinsu-co` auto-deploy → app healthy.
- **Verify prod:** Playwright login (claude-check@local), chạy đúng luồng 2 TP trên
  `co-case-0605189d5eea` (Johnson thật): calc TP1 → chốt TP1 → calc TP2 đều 200, lock render
  rev non-empty `af8cbf8...`, calc TP2 gửi rev đó → KHỚP, không còn "Origin case state
  changed". Reopen khôi phục (không tồn dư claim).

## Decisions Made
- Token chống sửa đồng thời chỉ nên phản ánh **state người dùng sửa**, không gồm dữ liệu phái
  sinh/refetch. Mất phát hiện sửa raw-field của product là chấp nhận được (autosave trả
  revision riêng + gating tuần tự là lớp bảo vệ chính).
- Revert in-flight guard `caseShellBusy` — nó fix một race khác (click trước khi swap 4MB
  settle, lỗi "Chỉ chốt được... sau khi đã tính"), KHÔNG phải #9. Giữ scope gọn.
- Deploy qua CI (push TinsuAI/co), không SSH tay — theo ý user.

## What Didn't Work
- Giả thuyết đầu "listener `change` bị nhân lên trên mỗi AJAX swap" → SAI: `<script>` nằm
  ngoài `[data-co-case-shell]` (đóng ~1688, script 1749-4894), IIFE chạy 1 lần.
- Không tái hiện được 409 ở **local/demo**: thiếu snapshot fast-path + dữ liệu nguồn tĩnh nên
  không drift; calculate đường chậm render `rev=""` → check bị skip. Phải dựa vào ảnh khách +
  verify post-fix trên prod.
- Push nhầm lên `sgnjfk/barry-CO-bom-builder` đầu tiên (remote sai, runner offline → kẹt
  queued). Đã chuyển sang TinsuAI/co.

## Open Items
- 6 mục feedback còn lại: #7, #8, #12, #14 (sửa nhanh–vừa), #13 (luồng mới, cần discover),
  #4 (đẩy Data Hub). Thứ tự đề xuất trong STATUS.md.
- Bug phụ `origin_calculation_lock` không nhả sau `/evaluate`+`/calculate` (chặn cross-case
  60-min TTL). Chưa tái hiện sống, chưa fix. Audit Gap 4.
- Test prod để lại `co-case-0605189d5eea` 2 sheet ở `calculated` (gốc `draft`) — benign.
- `.ai/STATUS.md` + feedback doc + session files chưa commit (để user quyết).
