# Feature: Số tồn tổng (tổng giá trị tồn CO, VNĐ) trên trang làm CO

Feedback khách #12 — "Không nhìn được số tồn tổng để kiểm soát". Đã làm rõ với khách:
con số mong muốn là **tổng GIÁ TRỊ tồn CO quy VNĐ**, hiển thị ở **trang làm CO ngoài
cùng** (`/clients/{id}/co-case`, danh sách hồ sơ).

## Scope (chốt với khách)
Một strip "Tồn CO để kiểm soát" ở **ĐẦU trang làm CO** (`/clients/{id}/co-case`,
trên command-bar "Làm hồ sơ C/O") gồm:
- **Tổng giá trị tồn tự do (VNĐ)** = Σ(còn-lại-sau-trừ-claim × đơn giá × tỷ giá→VNĐ).
- **Tổng số lượng tồn** = Σ free remaining, **gộp mọi đơn vị tính** (khách chấp nhận
  sai khác đơn vị; gắn nhãn "tham khảo").
- **Số mã** NVL còn tồn (distinct allocation_code/material_code, free remaining > 0).
- **Số dòng lot** còn tồn.

Kèm **filter khoảng ngày đăng ký tờ khai nhập** (`registration_date`, từ/đến) — đổi ngày
thì recompute cả 3 số (qua JSON endpoint, không reload trang).

Lý do giá trị VNĐ cho tiền (không cộng số lượng): mã khác đơn vị (kg/cái/m) không cộng
số lượng thành 1 scalar; tiền cộng được qua mọi UOM. "Tổng số đơn vị" → khách chọn **số
mã + số dòng lot** thay vì cộng số lượng.

KHÔNG làm: rollup per-code (đã có chip "{N} tồn" ở panel mã thay thế từ #8). KHÔNG đụng
trang Tồn CO (giữ scope ở trang làm CO như khách chỉ).

## Decisions
- **Phạm vi đếm:** chỉ lot **khả dụng** (eligible, allocation_code resolved, remaining>0)
  — đúng nghĩa "tồn còn dùng được để kiểm soát". Thực nghiệm johnson-vn: lọc khả dụng vs
  gộp tất cả cho **cùng con số** (~1.929 nghìn tỷ) vì dòng hết tồn cộng 0 — nên lọc an toàn,
  không méo số.
- **Trừ ledger sống:** `remaining_qty` đã fold trừ-lùi baseline nhưng CHƯA trừ claim
  cross-case đang giữ. Để khớp bảng Tồn CO + panel thay thế (cả 2 đều overlay ledger),
  trừ thêm giá trị các lot đang bị claim. johnson chỉ 216 claim → rẻ.
- **Tính bằng 1 câu SQL aggregate** trong `co_stock_materializer`, KHÔNG nạp 60k JSONB vào
  Python. LEFT JOIN `co_stock_rows` với subquery `co_stock_claims` (status active) gộp
  `claimed_qty` theo `(declaration_no,line_no,customs_code)` = `(import_declaration_no,
  line_no,customs_item_code)`; free = `max(remaining_qty − claimed, 0)`; value =
  `free × unit_value × coalesce(fx,1)`. Filter `registration_date between from and to`
  (ISO YYYY-MM-DD — johnson 0 dòng thiếu, so chuỗi an toàn). Lọc theo `client_id` (đã
  index) = vài ms với johnson 60k.
- **Endpoint JSON** `GET /clients/{id}/co-stock/summary?from=&to=` trả
  `{code_count, lot_count, total_value_vnd, currency}`; strip render ban đầu từ
  `co_case_context` (mặc định all-time), JS refetch khi đổi ngày.
- **Quy đổi VNĐ:** `unit_value × coalesce(exchange_rate_to_vnd, 1)`. johnson-vn 100% VND
  nên fx=1; coalesce giữ đúng cho client ngoại tệ về sau.
- **Hiển thị:** giữ "N dòng Tồn CO" (count) và thêm giá trị, ví dụ
  `… · 60.173 dòng Tồn CO · ≈ 1.929 tỷ ₫ tồn`. Số rút gọn (tỷ/triệu) + `title=` full số
  có dấu phân cách. Chỉ hiện khi có snapshot (>0 dòng).

## Risks
- **Hiệu năng render trang list:** đừng dùng `read_co_stock_rows_cached` (cold 2-3s nạp
  60k JSONB). Phải là SQL aggregate thuần. Đo lại sau khi gắn vào `co_case_context`.
- **Tính nhất quán số:** nếu chọn folded-remaining (không trừ ledger) thì headline sẽ
  hơi cao hơn tổng cộng từ bảng Tồn CO khi có claim sống. Quyết định ở trên: trừ ledger.
- **value_currency vs currency:** johnson cả hai = VND. Công thức dùng `unit_value` +
  `exchange_rate_to_vnd`. Nếu client nào `value_currency` lệch `currency` cần xác minh lại
  field nào là đơn giá gốc — hiện chưa có ca đó.
- **File-mode / client chưa materialize:** trả None/ẩn chip (không vỡ trang). do-thanh/
  growatt chỉ 1 dòng — số sẽ nhỏ/không có, benign.

## Open Questions (đã chốt)
1. ✅ Tồn còn TỰ DO (trừ claim) — khách chọn.
2. ✅ "Tổng số đơn vị" = số mã + số dòng lot.
3. ✅ Filter theo ngày đăng ký tờ khai nhập (registration_date).
- Định dạng tiền: rút gọn (≈ 1.929 tỷ ₫) + tooltip full số — mặc định, đổi nếu khách muốn.
- Không hiện ở trang Tồn CO (đúng chỗ khách chỉ).

## Next step
Standard feature: write tests → implement → /rev → commit. Mức rigor: vừa.
- Test: aggregate (giá trị/đếm), ledger-trừ-claim, filter ngày (in/out range), client
  rỗng/file-mode trả 0.
- Implement: hàm `co_stock_summary(client_id, date_from, date_to)` ở
  `co_stock_materializer`; endpoint summary; strip + date filter trên `co_case.html`;
  inject default vào `co_case_context`.
