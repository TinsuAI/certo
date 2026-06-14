# Changelog

Tất cả thay đổi đáng chú ý của Data Hub được ghi tại đây.
Định dạng theo [Keep a Changelog](https://keepachangelog.com/);
phiên bản theo [SemVer](https://semver.org/).

> Các phiên bản trước **0.13.0** được tái dựng từ lịch sử git + nhật ký
> phiên làm việc (`.ai/sessions/`). Giai đoạn pre-MVP chưa cắt tag, nên
> mốc phiên bản gom theo từng đợt tính năng chính, không phải bản phát
> hành đã đóng gói tại thời điểm đó.

## [Unreleased]

## [0.18.0] — 2026-06-14
### API
- **Đọc NXT / chốt tồn kho theo trang + lọc:** thêm endpoint `/v1/hub` lấy danh sách dòng có phân trang cho từng bảng NXT và từng bản chốt tồn kho (phục vụ artifact lớn như SAP MB5B ~20k dòng), kèm lọc theo mã / vai trò / kho và tổng số dòng chính xác. Lọc danh sách NXT theo năm quyết toán, danh sách chốt tồn kho theo năm. Hai endpoint trả toàn bộ dòng cũ giữ nguyên (additive). Chi tiết: `docs/API_CHANGELOG.md` (2026-06-14, Additive).

## [0.17.0] — 2026-06-14
### Mới
- **NXT theo năm quyết toán:** mỗi khách hàng một bảng NXT cho mỗi năm; bắt buộc nhập "Năm quyết toán" khi tải lên, tải lại cùng năm sẽ thay thế bản cũ. Chốt tồn kho bắt buộc nhập "Ngày chốt".
- **Xem dữ liệu đã ingest:** trang chi tiết cho từng bảng NXT và từng bản chốt tồn kho — xem toàn bộ dòng (có phân trang), tồn cuối suy ra / chênh lệch (sổ sách vs thực đếm) được tô khi lệch; click cả hàng ở danh sách để mở chi tiết. Danh sách NXT thêm cột "Năm".
- **Liên kết sang Danh Mục:** mã trong bảng NXT / chốt tồn kho link sang trang chi tiết của mã đó ở Danh Mục (khi mã có trong danh mục).

### API
- `/v1/hub` NXT (danh sách + chi tiết) thêm trường `period_year`. Chi tiết: `docs/API_CHANGELOG.md` (2026-06-14, Additive).

## [0.16.0] — 2026-06-14
### Mới
- Quản lý dữ liệu **Nhập-Xuất-Tồn (NXT)** và **Chốt tồn kho cuối kỳ**: nhóm "Quyết toán" mới trong view khách hàng, luồng tải lên → xem trước → xác nhận cho cả hai loại; tồn cuối / chênh lệch (sổ sách vs thực đếm) tự tính khi xem.
- Mẫu chuẩn hệ thống tải về cho NXT (3 sheet NVL/TP/BTP) và chốt tồn kho.
- Parser linh hoạt nhận nhiều định dạng ERP có sẵn: EZSOFT/3TSoft (Growatt), SAP MB5B (Johnson), MISA "Cân đối tồn kho" (Hồng Phúc/An), kiểm kê đa-kho (DKE) — tự nhận diện định dạng. Định dạng lạ: gán cột qua giao diện (có gợi ý bằng LLM), hệ thống ghi nhớ cho các lần sau.
- Trang quản trị "Adapter Quyết toán": xem các parser đã đăng ký và đặt parser mặc định theo từng khách hàng.

### API
- Thêm endpoint đọc cho hệ thống quyết toán (BCQT): danh sách/chi tiết NXT, danh sách/chi tiết chốt tồn kho, và đối chiếu tồn-cuối ↔ đầu-kỳ ↔ kiểm kê theo từng mã. Chi tiết: `docs/API_CHANGELOG.md` (2026-06-14, Additive).

## [0.15.0] — 2026-06-14
### Mới
- Trang chi tiết cho từng lần tải lên: metadata đầy đủ (người tải, SHA-256, kích thước, số dòng, kết quả parse), nút tải lại file gốc, và xem trước nội dung file (50 dòng đầu của xlsx/xls/csv) ngay trên trình duyệt.
- Bảng dữ liệu: click vào cả hàng để mở trang chi tiết (BCCT, Danh mục, BOM, Đề xuất, Tờ khai, Tải lên) thay vì phải bấm icon nhỏ ở cuối hàng.

### Cải tiến
- Điều hướng trong view khách hàng gom lại thành 3 nhóm domain (Danh mục · Hải quan · BOM); "Đề xuất" chuyển vào nhóm BOM cùng Định mức / Cần xử lý / Hệ số quy đổi.
- Trang Tải lên: thêm cột "Người tải" và Việt hoá nhãn trạng thái.
- Làm rõ chiều hệ số quy đổi UoM ở mọi nơi staff nhìn: gợi ý trên trang hệ số, tooltip cột, và sheet "Hướng dẫn" của template import. Quy ước: hệ số = 1 đơn vị "Từ" quy ra bao nhiêu đơn vị "Sang"; số lượng (Sang) = số lượng (Từ) × hệ số.
- Bước materialize BOM cảnh báo khi một mã leaf nhận nhiều đơn vị quy về canonical khác nhau (vd g và kg), tránh cộng số lượng khác đơn vị trước khi quy đổi.

### Sửa lỗi
- Trang hệ số quy đổi UoM: ô xem trước không còn hiện ra thành một ô trống vô duyên khi chưa nhập đủ "Từ UoM / Sang UoM / Hệ số" (CSS `display` đè lên thuộc tính `hidden`).
- Quy đổi UoM: khi chỉ khai hệ số một chiều (vd B→A), bước làm phẳng BOM nay tự suy chiều ngược (lấy nghịch đảo) — trước đây panel danh mục/cảnh báo báo "quy đổi được" nhưng làm phẳng vẫn báo thiếu hệ số.
- Template import hệ số UoM: sửa dòng mẫu bị ngược (EA→SETS hệ số 4 ⇒ nay là SETS→EA hệ số 4, khớp ghi chú "1 SETS = 4 EA").

## [0.14.0] — 2026-06-14
### Mới
- Phân loại "khả năng khai báo" (`customs_relevance`) cho từng dòng leaf của BOM — declarable / declarable_unmatched / non-declarable — theo mô hình hai lớp: (1) bằng chứng nhập khẩu từ BCCT (tổng quát, không cần cấu hình); (2) bản đồ Material Group theo từng khách hàng (tùy chọn, để gom rác). Cho phép lọc mềm dòng non-declarable khỏi bảng kê bằng cờ `exclude_non_declarable` theo từng khách hàng (mặc-định-OFF, không xóa gì — BOM bất biến). (mig 078/079)
- Quản lý "module" adapter BOM: trang Adapter BOM (registry) chỉ-xem liệt kê các parser đã đăng ký + tín hiệu mỗi adapter phát ra; UI bản đồ Material Group theo khách hàng; gán adapter mặc định theo từng khách hàng. (mig 080/081)
- Trang Khách hàng: ô tìm kiếm tức thì (lọc theo tên · mã · MST), badge chế độ khớp mã bằng tiếng Việt, lưới module thu gọn thành dải chip.
- Thanh điều hướng admin gom nhóm dùng chung mọi trang admin (Người dùng · Dữ liệu tham chiếu · Adapter BOM · Hệ thống), tự sáng mục đang mở; trang "Cài đặt embedding" trước đây mồ côi nay đã có lối vào.

### Cải tiến
- Việt hoá giao diện: nhãn tab (Tổng quan / Tải lên / Đề xuất / Cấu hình), chế độ khớp mã + chế độ duyệt hiển thị bằng tiếng Việt thay cho mã enum thô (batch_aggregate_resolution → "Gộp theo lô", …), bỏ tiếng Anh lẫn lộn trong mô tả module + đề xuất + tải lên.
- Top nav dọn gọn: nav khu vực dạng chữ bên trái (Khách hàng · Quản trị), bên phải gộp tên/vai trò/đổi ngôn ngữ/đăng xuất vào một menu avatar; bỏ breadcrumb (tên khách hàng đã nằm ở tiêu đề trang).

### Sửa lỗi
- BOM: chọn adapter dạng cây (sap_indented_walk / multi_sheet_per_root) qua binding theo khách hàng hoặc dropdown thủ công nay đi đúng đường raw_graph + materialize; trước đây bị lưu phẳng (manual_flat) và bỏ qua flatten (MPL0100-39).

## [0.13.1] — 2026-06-08
### Mới
- Thiết kế lại trang chuẩn ĐVT toàn cục + trang hệ số quy đổi theo từng khách hàng; bảng hệ số có phân trang.
- Panel "lệch ĐVT" trên trang chi tiết vật tư: phân loại tương đương / quy đổi được / cần xác nhận / không quy đổi được.

### Cải tiến
- Cảnh báo lệch ĐVT nhận biết khả năng quy đổi: BOM khác BCCT, hay các dòng BCCT khác nhau, đều được chấp nhận nếu quy đổi về nhau được (cùng họ đơn vị, có hệ số khách hàng, hoặc alias) — chỉ báo khi thật sự không quy đổi được. Hết báo động giả cho kg/g, m/cm, SETS/PCS.
- Cờ "BOM cũ" (staleness) chỉ bật khi ĐVT giữa BOM và danh mục không quy đổi được. Sửa ĐVT danh mục theo kiểu quy-đổi-được (ví dụ kg→g) không còn báo nhầm BOM cũ; số lượng cần xử lý giảm, sát thực tế hơn.

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
