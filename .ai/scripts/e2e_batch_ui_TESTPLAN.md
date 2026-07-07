# Kịch bản test — Batch "sheet tổng hợp" (thiếu tồn + thay NVL)

Server dev `:8001` (auth-ON — đăng nhập SSO như thường). Data hiện tại = 0 case, nên bước 0 **seed
1 case thiếu tồn** (giá trị cố định, tồn thật của growatt-vn).

---

## Bước 0 — Seed case thiếu tồn (chạy 1 lần)

```bash
cd ~/projects/co
set -a; . ./.env.dev; set +a
PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_ui_seed.py
```

Tạo case **`e2e-batch-ui`** dưới **`growatt-vn`**: 5 SP (SP-1…SP-5), mỗi SP cần **2000 kg** NVL
`940.0661900`; tồn CO ~**6000** → **thiếu 4000 kg**, thiếu ở **SP-4 & SP-5**. Script in ra rollup để đối chiếu.

Mở trong browser: **Growatt VN → hồ sơ `E2E-BATCH-UI` → bước "Bảng kê C/O"**
(URL: `/clients/growatt-vn/co-case/e2e-batch-ui/origin`).

---

## Các bước bấm + kết quả mong đợi

| # | Thao tác | Mong đợi (PASS nếu đúng) |
|---|---|---|
| 1 | Nhìn thanh công cụ bước Bảng kê | Có **"Chạy tồn (tất cả SP)"** + **"Chốt tất cả"** (bật, không còn "🚧 đang xây dựng") |
| 2 | Bấm **"Chạy tồn (tất cả SP)"** | Hiện panel: **phase ribbon** (Tính cả lô › **Xử lý thiếu tồn** › Review & Chốt) + "⚠ **1 NVL thiếu tồn** trên cả lô" + note "Phân bổ tồn: SP trước ưu tiên…, lot theo ngày tờ khai" |
| 3 | Xem dòng NVL | **`940.0661900`** · cần **10000** · tồn **6000** · **thiếu 4000 kg** · chip **[thiếu 2/5 SP]** (đơn vị *kg* phải hiện, không chỉ số SP) |
| 4 | Bấm **"Thay hết · 5 SP"** | Toggle chuyển highlight sang "Thay hết"; "Thay phần thiếu · 2 SP" bỏ highlight |
| 5 | Bấm mũi **▸** đầu dòng NVL | Mở **drill-down**: 5 ô SP — SP-1/2/3 chấm **xanh** + LVC; SP-4/5 chấm **cam** + "thiếu … kg" |
| 6 | (Để scope "Thay hết") Bấm **"Chọn mã thay thế…"** | Mở **đúng modal thay thế** (như sheet con): tiêu đề **"Thay NVL 940.0661900 · Thay hết · 5 SP"** (⚠ phải theo scope, KHÔNG phải "SP SP-4"); có card NVL hiện tại, 2 tab **Khuyến nghị / Tìm kiếm**, ô Lọc nhanh, "Chỉ hiện mã đủ tồn" |

**Bước 1–6 test được đầy đủ trên case seed này.** (Đây là phần UI chính: bảng material-centric, đơn vị
thiếu, scope toggle, drill-down, modal nhất quán + label theo scope.)

---

## Phần cần CASE THẬT (DH-BOM) — không chạy được trên case seed

Case seed synthetic nên: (a) tab **Khuyến nghị** có thể trống ("Chưa có khuyến nghị từ Data Hub" — NVL
này chưa map ở DH local); (b) sheet con hiện "chưa có BOM". Đây là **giới hạn data, không phải lỗi UI**.

Để test **apply → tính lại → sheet con update → Chốt tất cả**, dùng **1 case có BOM Data Hub thật**
(vd sản phẩm `PV00.0048500` của growatt — có DH BOM #3), tạo qua luồng bình thường (nhập TKX/invoice →
load BOM) sao cho có NVL thiếu tồn, rồi:

| # | Thao tác | Mong đợi |
|---|---|---|
| 7 | Trong modal (case thật), chọn 1 mã khuyến nghị → **Áp dụng** | Modal đóng; toast "Đã thay … ở N SP"; **server tính lại** — nếu mã thay **đủ tồn** → dòng NVL biến mất/bớt thiếu; nếu mã thay **vẫn thiếu** → dòng vẫn hiện với số **tính lại** |
| 8 | Sau khi thay, mở tab **sheet con** vừa bị đụng | Sheet con hiện **"→ mã-thay-thế"** (đồng bộ, không cần tải lại — shell tự swap) |
| 9 | Khi hết thiếu tồn → bấm **"Chốt tất cả"** | Chốt các sheet đã tính theo thứ tự; báo số chốt / bỏ qua; **sheet còn NVL chưa khớp tồn (declarable_unmatched) bị chặn** (guard DC3c) |
| 10 | (Consistency) Thay ở tab khác/đổi thứ tự rồi thao tác lại | Không "Hồ sơ đã đổi" sai (revision-token tự cập nhật); số đủ/thiếu luôn khớp server |

---

## Dọn sau khi test

```bash
cd ~/projects/co
set -a; . ./.env.dev; set +a
PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_ui_seed.py --cleanup
```

## Ghi chú
- Đã browser-verify sẵn (headless): bước 1–6 PASS + label scope (FU1), 0 lỗi JS (chỉ favicon-404).
  Screenshots: `.ai/screenshots/2026-07-07-batch-ui-e2e/`.
- Bước 7–10 (apply/sync/chốt) verify server-side rồi (bulk-substitute + re-allocation đúng trên tồn thật),
  chỉ chưa e2e-browser vì thiếu case DH-BOM local — nên nhờ ông spot-check trên case thật / nightly.
