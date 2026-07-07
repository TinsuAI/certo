# Kịch bản test — Batch "sheet tổng hợp" (thiếu tồn + thay NVL)

Server dev `:8001` (auth-ON — đăng nhập SSO).

## Bước 0 — Case ĐÃ SEED SẴN (BOM Data Hub thật)

Đã seed sẵn case **`e2e-batch-real`** dưới **growatt-vn**: 5 SP đều dùng BOM thật **`INV-5000`** (7 NVL từ
Data Hub), tồn `co_stock_rows` được seed để **AL-100 thiếu 2/5 SP**, 6 NVL còn lại đủ.

1. **Đăng nhập** `:8001` bằng SSO (tài khoản dev/admin — để thấy client `growatt-vn` + phiên có DH token).
2. Mở: `http://127.0.0.1:8001/clients/growatt-vn/co-case/e2e-batch-real/origin`
   (hoặc Growatt VN → hồ sơ `E2E-BATCH-REAL` → bước "Bảng kê C/O").
3. Sheet phải hiện **BOM INV-5000** (7 NVL) — KHÔNG còn "chưa có BOM". (BOM kéo từ DH bằng **phiên của
   ông**; nếu vẫn "chưa có BOM" → báo tôi, do phiên/BOM fetch.)

**Con số thiếu tồn kỳ vọng** (đã verify bằng đường tính không-phiên): NVL **AL-100** · **cần 1000 · tồn
600 · thiếu 400 kg · thiếu 2/5 SP (SP-4, SP-5)**. (0.5 kg/SP × 400 × 5 = 1000; tồn 600 đủ SP-1..3.)

> Re-seed / dọn: `set -a; . ./.env.dev; set +a; PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_real_seed.py [--cleanup]`
> (chỉ ghi DB CO; xoá tồn theo marker `transaction_key='e2e-batch-real…'`, không đụng tồn khác / DB Data Hub).

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
