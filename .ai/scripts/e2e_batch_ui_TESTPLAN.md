# Kịch bản test — Batch "sheet tổng hợp" (thiếu tồn + thay NVL)

Server dev `:8001` (auth-ON — đăng nhập SSO).

> **Vì sao KHÔNG seed bằng script:** app gọi Data Hub bằng **token phiên đăng nhập** của user
> (`current_data_hub_token()`), không có service-token. Script (không có phiên) → không kéo được BOM
> từ DH → chỉ tạo được case "giả" nhét NVL inline, nhưng sheet sẽ hiển thị **"chưa có BOM"** (không
> thực tế). Muốn test đúng phải dùng **case có BOM Data Hub thật** — chỉ tạo được khi **đã đăng nhập**.

---

## Bước 0 — Có 1 case CÓ BOM THẬT + thiếu tồn

Đăng nhập `:8001` rồi **tạo/mở 1 case CO qua luồng bình thường** sao cho có NVL thiếu tồn:
1. Tạo hồ sơ CO cho **growatt-vn** (hoặc johnson-vn).
2. Nhập TKX/chứng từ → app match BCCT + **load BOM** cho các SP.
3. Chọn **≥2 SP dùng CHUNG ≥1 NVL** mà **tồn CO không đủ** cho tổng nhu cầu → sẽ có thiếu tồn.
   (Mẹo tạo thiếu tồn chắc chắn: chọn SP có sản lượng/định mức lớn trên 1 NVL tồn thấp.)

> Nếu không tiện tạo case thiếu tồn thật ở local → **test trên nightly** (`demo-co`) có data thật,
> hoặc chỉ cần 1 NVL bất kỳ thiếu tồn là đủ để thấy bảng tổng hợp.

Mở case → bước **"Bảng kê C/O"**.

---

## Các bước bấm + kết quả mong đợi

| # | Thao tác | Mong đợi (PASS nếu đúng) |
|---|---|---|
| 1 | Thanh công cụ bước Bảng kê | Có **"Chạy tồn (tất cả SP)"** + **"Chốt tất cả"** (đã bật, hết "🚧 đang xây dựng") |
| 2 | Bấm **"Chạy tồn (tất cả SP)"** | Panel: **phase ribbon** (Tính cả lô › **Xử lý thiếu tồn** › Review & Chốt) + "⚠ N NVL thiếu tồn" + note "Phân bổ tồn: SP trước ưu tiên…, lot theo ngày tờ khai" |
| 3 | Xem 1 dòng NVL thiếu | `<mã>` · **cần X · tồn Y · thiếu Z <đơn vị>** · chip **[thiếu a/b SP]** (⚠ **đơn vị** phải hiện, không chỉ số SP) |
| 4 | Bấm **"Thay hết · b SP"** ↔ **"Thay phần thiếu · a SP"** | Highlight chuyển đúng |
| 5 | Bấm **▸** đầu dòng NVL | Drill-down: mỗi SP dùng NVL = 1 ô — đủ tồn (xanh + LVC) / thiếu (cam + "thiếu … <đv>") / 🔒 đã chốt / đỏ = chặn |
| 6 | (scope "Thay hết") Bấm **"Chọn mã thay thế…"** | Mở **đúng modal thay thế** như sheet con: tiêu đề **"Thay NVL <mã> · Thay hết · b SP"** (theo scope, KHÔNG phải "SP <1 SP>"); card NVL hiện tại; 2 tab **Khuyến nghị / Tìm kiếm** + Lọc nhanh + "Chỉ hiện mã đủ tồn" |
| 7 | Chọn 1 mã khuyến nghị → **Áp dụng** | Toast "Đã thay … ở N SP"; **server tính lại**: mã thay đủ tồn → dòng biến mất/bớt thiếu; mã thay **vẫn thiếu** → dòng vẫn hiện với số **tính lại** (mã thay cũng được phân bổ tồn) |
| 8 | Mở tab **sheet con** vừa bị đụng | Sheet con hiện **"→ mã-thay-thế"** (đồng bộ, không cần tải lại — shell tự swap) |
| 9 | Khi hết thiếu tồn → **"Chốt tất cả"** | Chốt các sheet đã tính theo thứ tự; báo số chốt/bỏ qua; **sheet còn `declarable_unmatched` bị CHẶN** (guard DC3c) |
| 10 | (Consistency) Thay/đổi thứ tự rồi thao tác lại | Không "Hồ sơ đã đổi" sai (revision-token tự cập nhật); số đủ/thiếu luôn khớp server |

---

## Đã verify sẵn (headless, trên tồn thật)
Bảng material-centric render + **đơn vị thiếu** + phase ribbon + scope toggle + drill-down 5 ô SP +
modal label theo scope (FU1) — **PASS, 0 lỗi JS** (chỉ favicon-404). Screenshots
`.ai/screenshots/2026-07-07-batch-ui-e2e/`. (Panel render đúng dù case dùng để chụp là case-render nội bộ.)
Bước 7–10 verify server-side (bulk-substitute + re-allocation đúng) — cần case DH-BOM thật để e2e-browser.

> `e2e_batch_ui_seed.py` chỉ để **smoke render nội bộ** panel tổng hợp (case synthetic, sheet sẽ "chưa
> có BOM"); **KHÔNG dùng làm case test thật**.
