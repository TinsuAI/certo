# Feature: Mục 4a — auto/bulk áp hệ số chi phí + UI tự-giải-thích

Client feedback item 4a: "auto phân bổ chi phí trực tiếp theo tỷ lệ cố định per-client vào
bảng kê RVC." Builds **on top of** the shipped cost-allocation system
(`.ai/features/2026-05-27-cost-allocation-ratios/`) — the engine (hệ số × FOB → 6 chi tiết →
II/III/VII, lợi nhuận V suy residual), admin page, Excel import, Mode A/B fallback, and the
per-product "Áp hệ số" button all already exist and work. This feature adds the deferred
**"auto" layer** (the 2026-05-27 brief explicitly put "auto-recompute" + bulk apply in *Out*)
**and** makes the Mode A→B→none flow legible in the UI (user request: "trên UI cũng phải rõ ràng").

## Scope

In:
- **Bulk apply** across a case: one action áp hệ số (Mode A per Mã SP → Mode B default fallback)
  × FOB cho **mọi SP có tiêu chí RVC/LVC** trong hồ sơ, điền 6 chi tiết cost_buildup + lưu, in one go.
- **Coverage/result surfacing** so the user understands what happened: per-SP cho biết đã áp
  Mode nào (A theo mã / B mặc định DN / chưa có hệ số), và **liệt kê rõ SP nào chưa có hệ số**
  (skip, không điền 0 âm thầm) để user biết vào Cấu hình hệ số bổ sung hoặc nhập tay.
- **Clarify the existing per-product UX**: phân biệt rõ "hệ số" (vd 0.03) vs "số tiền đã áp"
  (0.03 × FOB); badge/nhãn Mode A vs B; chỉ dẫn khi không có hệ số.
- Server-side bulk endpoint (auditable, atomic per case) reusing the existing resolve +
  cost_buildup persist paths. Per-product button stays for fine adjustments.

Out:
- Thay đổi công thức calc (hệ số × FOB, rollup II/III/VII, lợi nhuận V residual) — KHÔNG đổi.
- Auto-apply âm thầm lúc xuất/tính bảng kê (rejected: lệch triết lý explicit/auditable; reviewer
  hải quan cần thấy được nguồn số). Bulk vẫn là hành động explicit do user bấm.
- Auto-recompute khi FOB đổi (vẫn idempotent, áp lại thủ công nếu FOB đổi — như v1).
- Versioning hệ số theo thời gian; multi-currency rules (FOB currency giữ nguyên).
- Thêm UI cấu hình hệ số mới — trang admin `/clients/{id}/cost-allocation` đã đủ.
- Đổi layout bảng kê I–VIII (6 chi tiết vẫn là nội bộ CO).

## Decisions (proposed — confirm during build)

- **Trigger = nút bulk explicit** ("Áp hệ số cho tất cả SP RVC/LVC"), KHÔNG auto im lặng. Khớp
  theme "chạy 1 lần / chốt tất cả" của Mục 6; giữ tính minh bạch của hệ thống hiện có.
- **Fallback giữ nguyên** `get_ratio`: Mode A (theo `product.bom_product_code or product.code`)
  → Mode B (`product_code=''`) → None. SP rơi vào None = **skip + báo**, không điền 0.
- **Overwrite có cảnh báo**: nếu có SP đã nhập tay cost_buildup, bulk hỏi xác nhận trước khi ghi đè
  (giống confirm của nút per-product). Cân nhắc: chỉ áp cho SP đang trống + tùy chọn "ghi đè tất cả".
- **FOB nguồn = `product.fob` raw** (native currency) — đúng cái nút per-product đang dùng
  (`panel.dataset.productFob`). Lợi nhuận V vẫn để trống (engine suy).
- **Persist** qua đúng đường merge cost_buildup hiện có (origin save/autosave, whitelist 6 key)
  để không tạo write-path thứ hai.
- **UI rõ ràng**: kết quả bulk = summary "Đã áp X SP (n Mode A, m Mode B) · Y SP chưa có hệ số: …",
  có link sang trang Cấu hình hệ số. Per-product status line giữ + làm rõ wording hệ số↔số tiền.

## Risks

- **Calc-parity (high-risk area)**: tuyệt đối không đổi công thức; bulk chỉ là vòng lặp gọi cùng
  hàm resolve/apply của đường per-product. Regression test so khớp bulk-1-SP == nút per-product.
- **Nguồn FOB & currency**: phải dùng đúng FOB native (giống per-product). SP thiếu FOB (fob rỗng/0)
  → coef × 0 = 0 ⇒ nên **skip + báo "thiếu FOB"** thay vì điền 0. Cần xử lý.
- **Mode B vắng (Growatt)**: file Growatt toàn Mode A; nếu chưa cấu hình Mode B thì SP ngoài 24 mã
  sẽ skip. Đây là hành vi đúng nhưng UI phải nói rõ để user không tưởng bug.
- **Ghi đè dữ liệu nhập tay**: bulk có thể xóa số user đã chỉnh. Mặc định an toàn = chỉ điền SP trống,
  ghi đè phải opt-in/confirm.
- **File-mode persistence**: hệ số đọc DB → JSON fallback (`config/cost-allocation/<client>.json`)
  nên dev không-DB vẫn chạy; nhưng case cost_buildup persist phụ thuộc store hiện hành (xác nhận
  ở demo/test). `get_app_state_store()` Postgres-only KHÔNG liên quan ở đây (đây là cost_buildup
  trên case, không phải client overlay).
- **Chỉ RVC/LVC**: bulk phải lọc đúng SP có tiêu chí RVC/LVC (giống điều kiện hiện nút per-product),
  bỏ qua CTH/CTC/PSR.

## Resolved (sau demo trực quan 2026-06-18)

Demo (`.ai/screenshots/2026-06-18-cost-allocation-demo/`) xác nhận: engine + clarity per-product
ĐÃ tốt (modal ⚙ hiện rõ Mode A/B/none + status + tổng chi phí). Gap thật = thiếu **cái nhìn cấp
hồ sơ + thao tác 1 lần** (phải mở từng modal ⚙, không có bảng coverage tổng).

1. **Đặt nút**: cấp bước 3 (đầu danh sách SP) — thanh bulk + bảng coverage per-SP.
2. **Ghi đè**: mặc định **chỉ điền SP đang trống**; SP đã nhập tay → liệt kê + **confirm** trước khi
   ghi đè. (giống confirm per-product hiện có).
3. **Preview**: KHÔNG có bước preview-trước-commit riêng. Bảng coverage luôn hiện sẵn (badge Mode
   A/B/chưa-có/thiếu-FOB) + **summary sau khi áp** ("Đã áp 5 SP: 3 A, 2 B · 2 chưa có: X, Y") là đủ.
4. **SP thiếu FOB**: skip + báo "thiếu FOB", không điền 0.

## Final shape

- **UI bước 3**: thanh "Áp hệ số cho tất cả SP (RVC/LVC)" + bảng coverage (mỗi SP RVC/LVC: badge
  mode + đã-áp?/trống + link Cấu hình hệ số). Modal per-product giữ nguyên để chỉnh tay.
- **Server**: bulk endpoint duyệt SP RVC/LVC → `get_ratio` (A→B) × `product.fob` → điền SP trống
  (hoặc ghi đè khi confirm) → lưu qua đường merge cost_buildup hiện có → trả summary
  {applied:[{code,mode}], skipped_no_ratio:[...], skipped_no_fob:[...], skipped_filled:[...]}.

## Next step

`/tdd`: test-first cho bulk endpoint (regression: bulk-1-SP == nút per-product `apply_to_fob`);
xử lý A→B→none + thiếu FOB + chỉ-điền-trống/ghi-đè; rồi UI bước 3 + e2e screenshot. Vùng
calc-parity → không đổi công thức, chỉ bọc vòng lặp quanh hàm resolve/apply hiện có.
