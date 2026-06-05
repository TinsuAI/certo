# Customer feedback — HIỆN TRẠNG BARRY CO (2026-06-05)

Source: `P:\Downloads\HIỆN TRẠNG BARRY CO.pdf` (khách Johnson VN gửi). 14 mục thực chất (mục 15 trống; trang 5-25 trống). Cột "trạng thái" trong PDF là khách tự đánh dấu.

Legend: ✅ DONE · 🔧 fixed this session · ⬜ open · ⚠️ partial/đang vướng

| # | Nội dung | Khách đánh dấu | Trạng thái thực tế | Ghi chú / hướng làm |
|---|---|---|---|---|
| 1 | Chưa có mục xóa hồ sơ | DONE | ✅ | |
| 2 | Bước "mở" load hơi lâu | DONE | ✅ | |
| 3 | Thỉnh thoảng lỗi, không đề xuất được mã NVL thay thế | DONE | ✅ | |
| 4 | Mã NVL thay thế đề xuất chưa phù hợp | "VẪN CHƯA OK LẮM" | ⚠️ open | Ranking do **Data Hub** quyết (`data_hub_client.py:337`); heuristic CO hầu như vô dụng. Cải thiện phải ở DH, gửi qua `.ai/api-requests/`. Xem [[substitute-heuristic-dead-path]]. #8 sẽ giảm bớt cảm giác này. |
| 5 | Muốn nhiều bộ lọc cùng lúc | DONE | ✅ | |
| 6 | Chọn nhiều dòng để làm cùng 1 lệnh (xóa…) | DONE | ✅ | Xem [[bangke-bulk-row-delete]] |
| 7 | Không xem được toàn bộ tên hàng để chọn | (trống) | 🔧 **fixed (local)** | `.origin-substitute-item-name` giờ có `title=` (tooltip full tên) + cho xuống tối đa 2 dòng (`-webkit-line-clamp:2`) thay vì cắt 1 dòng ellipsis. Verify Playwright local: title present, line-clamp=2. |
| 8 | Bỏ đề xuất, chỉ gợi ý mã **đủ tồn**? | (trống) | 🔧 **fixed (local)** | Thêm toggle "Chỉ hiện mã đủ tồn" trên tab Khuyến nghị (tùy chọn, mặc định tắt). Quy tắc: ưu tiên feasibility "Đủ tồn" khi có ĐM, fallback `total_remaining_qty>0` đọc **live candidate** (stock nạp async qua `mergeLazyStock`, không dùng snapshot lúc build). Re-apply filter sau khi stock load. Verify local: visAfter khớp đúng số mã feasible. |
| 9 | Mỗi lần load BOM xong phải F5 mới load BOM tiếp | (trống) | 🔧 **FIXED + deployed prod** | Root cause: `origin_case_revision` hash các snapshot phái sinh biến động → action sau khi chốt sheet 409 "Origin case state changed". Fix: token chỉ hash state người dùng. Commit `9bb855c`. Verify prod OK. Xem [[bom-load-race-no-inflight-guard]]. |
| 10 | Em không xuất được bảng kê | DONE | ✅ | Xem [[bangke-export-non-numeric-unitvalue]] |
| 11 | Datahub đã có tờ khai mà Barry CO báo thiếu | DONE | ✅ | Xem [[tkx-tkn-missing-cached-context]] |
| 12 | Không nhìn được số tồn **tổng** để kiểm soát | (trống) | ⬜ open | Hiện chỉ có tồn theo từng lô/mã; chưa có SUM tổng (`co_stock.py` chỉ đếm bucket). Thêm aggregate ở trang CO-stock và/hoặc panel thay thế. |
| 13 | Chốt BOM 1 loạt → chạy tồn 1 lần → tổng hợp mã thiếu → thay định mức | (trống) | ⬜ open (lớn) | Thay đổi **luồng làm việc**, cần `/discover` thiết kế. Đáng giá nhất về năng suất. |
| 14 | Bước chọn BOM cho chọn **mặc định**, đến mã đó tự auto dùng | (trống) | ⬜ open | Backend đã có `bom_product_artifact_overrides` (per-product) nhưng chưa persist làm mặc định tái dùng giữa hồ sơ. Cần quyết định lưu ở đâu (per-client/global). |

## Đã làm session này
- **#9 fixed + deployed lên prod** (TinsuAI/co `9bb855c`, CI xanh, app healthy), verify đúng luồng 2 TP trên dữ liệu Johnson thật → hết "Origin case state changed", không phải F5. Regression test: `tests/test_origin_case_revision.py`.

## Phát hiện thêm (không nằm trong feedback)
- **Bug phụ — `origin_calculation_lock` không nhả:** `/evaluate` + `/calculate` acquire khóa per-client (60-min TTL) nhưng không release (chỉ close/reopen/origin-lock-release nhả). Chặn tính **hồ sơ khác cùng khách** tới 60 phút. Cùng-hồ-sơ thì OK (idempotent). Severity thấp–trung, tự lành. **Chưa tái hiện sống**, chưa fix. Xem audit `.ai/audits/2026-05-28-case-sheet-stock-state-machine.md` Gap 4.

## Đề xuất thứ tự session sau
1. #7 + #8 (sửa nhanh, cải thiện rõ) → 2. #12 → 3. #14 → 4. #13 (cần discover) → 5. #4 (đẩy Data Hub) → 6. cân nhắc fix bug lock.
