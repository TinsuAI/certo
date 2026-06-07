# Changelog

Tất cả thay đổi đáng chú ý của Data Hub được ghi tại đây.
Định dạng theo [Keep a Changelog](https://keepachangelog.com/);
phiên bản theo [SemVer](https://semver.org/).

> Các phiên bản trước **0.13.0** được tái dựng từ lịch sử git + nhật ký
> phiên làm việc (`.ai/sessions/`). Giai đoạn pre-MVP chưa cắt tag, nên
> mốc phiên bản gom theo từng đợt tính năng chính, không phải bản phát
> hành đã đóng gói tại thời điểm đó.

## [Unreleased]

## [0.13.0] — 2026-06-07
### Mới
- Trang "Có gì mới" hiển thị nhật ký thay đổi cho mọi người dùng.
- Hiển thị phiên bản ứng dụng (semver + mã commit) ở chân trang.
- Endpoint GET /version công bố phiên bản đang chạy.
- Khối tóm tắt BOM trên /source-summary (độ phủ xuất khẩu).

### Cải tiến
- Đồng bộ giao diện với hệ thiết kế "Primer console" của Barry CO.
- Dấu hiệu nhận diện ứng dụng: monogram xanh lá + khung viền 4 cạnh.
- Xếp hạng adapter theo điểm khớp; cảnh báo vật tư đa vai trò khi tải lên.
- Thông báo lỗi phân tích thân thiện hơn.

## [0.12.0] — 2026-06-06
### Mới
- Gộp tờ khai TKN/TKX thành một PDF chuẩn in (download.pdf).
- Nút "Render PDF còn thiếu" chạy nền.
- Tự phục vụ thu hồi phiên bản BOM + xóa upload lỗi.

### Cải tiến
- Surface các tờ khai đã đăng ký nhưng thiếu file gốc.

### Sửa lỗi
- Bắt buộc đăng nhập và chặn CDN cache khi tải file tờ khai (rò rỉ truy cập).

## [0.11.0] — 2026-06-05
### Mới
- Tìm kiếm khớp cả mã linh kiện/NVL, không chỉ mã sản phẩm.
- Tự động ánh xạ cột cho file tin cậy, bỏ qua bước map thủ công.
- Cấu hình alias cột theo từng khách hàng + trang quản trị.
- Hỗ trợ file không có dòng tiêu đề (ánh xạ theo vị trí cột).

### Cải tiến
- Adapter dạng cây tải lên thành raw_graph thay vì flat.
- Lưới phát hiện bất thường khi cột giá bị đảo; phản hồi upload trung thực hơn.

## [0.10.0] — 2026-05-31
### Mới
- Endpoint gộp POST /v1/hub/products/bom/artifacts:batch (gom ~150 lệnh gọi của CO còn 1).
- Quản lý token tài khoản dịch vụ: chọn/hiển thị hạn + tự gia hạn trượt.
- Kéo dữ liệu tăng dần cho CO (`since` + `include_tombstones`).
- Bản mirror Bearer của declarations download.zip.

### Gỡ bỏ
- Bỏ URL alias BOM vocab v1 (308 → 404) — thay đổi phá vỡ.
- Bỏ cột không dùng materials.category_override / override_reason — thay đổi phá vỡ.

## [0.9.0] — 2026-05-27
### Mới
- Chuỗi thời gian BCCT theo từng vật tư trên trang chi tiết.
- Tải lên hàng loạt qua ZIP (XLS/PDF theo từng tờ khai).
- Mô hình staleness có điều kiện + cột trạng thái; trang "cần xử lý" theo cụm.
- Cột NK/BOM-only + xuất Excel trên trang artifact phẳng.

### Cải tiến
- Gom near-duplicate tên hàng để giảm nhiễu drift; backup đầy đủ + restore drill.

## [0.8.0] — 2026-05-15
### Mới
- Nhập BOM khai hải quan theo Mẫu 16 (manual_flat).
- Hàng đợi rà soát xung đột tại /catalog/conflicts.
- Trạng thái file tờ khai + tải ZIP hàng loạt cho CO.

### Cải tiến
- Bulk materialize + nhập Mẫu 16 đều áp quy đổi UoM và phát tín hiệu drift.

## [0.7.0] — 2026-05-12
### Mới
- Onboarding Johnson: tờ khai, AI danh mục, vật tư thay thế, việc nền.
- Endpoint bcct/by-codes cho CO suy ra tồn kho thay thế.

### Cải tiến
- Hợp nhất materials.unit → uom (mã chuẩn duy nhất).
- Dedup các lát BTP đa vị trí; mirror tra cứu vật tư thay thế tại /v1/hub/* (Bearer cho CO).

### Sửa lỗi
- Parser SAP-indented lấy đúng lượng theo từng cha (MENGE), không lấy lũy kế (MNGKO).

## [0.6.0] — 2026-05-10
### Mới
- Multi-source: provenance, audit, vai trò dual-source, "mã chờ duyệt".
- Cổng kiểm UoM drift tại thời điểm nhập (BOM + BCCT), 3 mức nghiêm trọng.
- Track D — cờ phụ thuộc lỗi thời (staleness) + tuyến refresh; refresh quy đổi UoM theo chính sách 3 tầng.
- lineage_root_id định danh tuple phiên bản logic.

### Cải tiến
- Dọn từ vựng (template + i18n); admin UI cho client_uom_overrides; harness bất biến thứ tự nhập.

## [0.5.0] — 2026-05-08
### Mới
- Bộ định danh sản phẩm/vật tư chuẩn + hàng đợi rà soát.
- Engine luật phân tích cấu hình theo từng khách hàng.
- Phân loại btp_sourcing + UI danh mục + huy hiệu đa vai trò.
- View vai trò vật tử (v_material_roles) + cảnh báo xung đột toàn vẹn.

### Cải tiến
- Đẩy payload JSONB → cột định kiểu (Tier 1/2) + cắt khóa trùng; resolver Stage 2 (bóc trong ngoặc) thắng Stage 1.

## [0.4.0] — 2026-05-06
### Mới
- Mô hình BOM v3 ba shape + pipeline nhập theo lô nhà cung cấp.
- Xuất/nhập theo từng khách hàng + cờ dữ liệu tham chiếu.
- Nhãn cha người-đọc-được + panel lineage trong UI phiên bản.

### Cải tiến
- Phát hiện BTP cho dạng Johnson (cây sâu theo file nhà cung cấp); giữ first_seen, demote có kiểm soát.

## [0.3.0] — 2026-05-04
### Mới
- Phân trang + sắp xếp + tìm kiếm cho mọi bảng dữ liệu (BCCT, danh mục, BQD, BOM).
- Stack Docker Compose cho demo + backup nhận biết Compose.

### Cải tiến
- Connection pool psycopg (reset khi trả kết nối); lưu raw edges kỹ thuật.

## [0.2.0] — 2026-05-03
### Mới
- Engine flatten BOM thuần + thư viện UoM + phân loại + định danh.
- Registry adapter BOM cắm-được; nhập technical_flatten + preview thiết kế lại.
- Luồng ánh xạ hợp nhất (catalog / BQD / BOM manual_flat / BCCT).
- Rà soát đề xuất thủ công + hybrid; kill-switch API auth chỉ cho dev.

### Sửa lỗi
- Cắt đuôi .0 ở các trường khóa BCCT; backfill 6 cột BCCT bị parser cũ gán sai.

## [0.1.0] — 2026-04-30
### Mới
- Bản scaffold đầu tiên: quản lý hồ sơ khách hàng, danh mục NVL/SP/BTP,
  BOM, tờ khai hải quan (BCCT), đăng nhập SSO.
