# Training Demo: Data Hub và C/O

Ưu tiên buổi demo: Data Hub trước, C/O sau. Mục tiêu là cho người dùng thấy Data Hub là nơi quản lý dữ liệu gốc của DNCX: Danh Mục, BQD, BCCT, BOM, hồ sơ tờ khai, quyền truy cập, API cho hệ thống C/O và BCQT.

## Thông tin demo

- URL Data Hub: `http://127.0.0.1:8754`
- Tài khoản dev: `admin@data-hub.local / admin123`
- Công ty demo đã tạo: `Demo Precision Manufacturing VN`
- Client ID: `demo-precision-manufactu-68f7`
- Mã số thuế: `0312345678`
- Mode mã hàng: `identity` (`Mã HQ == Mã NB`)
- BOM proposal mode: `auto`

File demo:

| File | Đường dẫn | Nội dung |
|---|---|---|
| Danh Mục | `.ai/features/2026-05-04-demo-company-feed/input/demo_catalog_50_codes.xlsx` | 50 mã: 34 NVL, 7 BTP, 8 TP, 1 CCDC |
| BQD | `.ai/features/2026-05-04-demo-company-feed/input/demo_bqd_identity_50_codes.xlsx` | 50 cặp mapping identity |
| BCCT | `.ai/features/2026-05-04-demo-company-feed/input/demo_bcct_1000_rows.xlsx` | 1.000 dòng: 650 nhập, 350 xuất |
| BOM | `.ai/features/2026-05-04-demo-company-feed/input/demo_bom_multilevel_technical.xlsx` | BOM đa cấp, 15 sản phẩm/BTP được flatten |

Bộ tình huống nhập liệu phụ:

- Thư mục: `docs/training/input-scenarios/`
- README: `docs/training/input-scenarios/README.md`
- Regenerate: `uv run python scripts/generate_training_input_scenarios.py`
- Mục đích: demo header tiếng Anh, header nằm dòng 5, skipped rows, BCCT update diff, upload nhầm module, BOM manual flat, BOM technical flatten, SAP exploded BOM.

Kết quả hiện tại sau khi feed:

- Catalog: 50 dòng (`34 nvl`, `7 btp_sx`, `8 tp`, `1 ccdc`)
- BQD: 50 cặp identity
- BCCT: 1.000 dòng (`650 import`, `350 export`)
- BOM: 15 sản phẩm flattened, 97 dòng flattened, 0 unresolved node

## Danh sách feature cần demo

### Data Hub

1. Đăng nhập, đổi ngôn ngữ, đổi theme, notification bell.
2. Danh sách công ty, tạo công ty, chỉnh cấu hình công ty.
3. Workspace theo công ty: các module và tình trạng dữ liệu.
4. Cấu hình loại hình tờ khai: import `E11,E31`, export `E62,B11`.
5. Parser rules: cấu hình cách nhận mã nội bộ từ tên hàng khi khách dùng dual-code.
6. Danh Mục: list, search, filter, column display, detail, edit, tombstone/promote.
7. Upload Danh Mục: mapping cột, preview, confirm, HQ registered flag.
8. Mã chờ duyệt: phát hiện mã mới từ BCCT/BOM/BQD, accept/reject.
9. Substitute NVL: xem gợi ý thay thế, reject/unreject/manual add, refresh substitutes.
10. BQD: list mapping, upload mapping, preview, manual add.
11. BCCT: list, filter, sort, pagination, column picker, material identity.
12. Upload BCCT: mapping, preview diff, confirm, history từng dòng.
13. Hồ sơ tờ khai: danh sách TKX/TKN, upload file gốc PDF/XLS/XLSX, detail, delete.
14. BOM: list sản phẩm, artifact list, artifact detail, lineage, preset.
15. Upload BOM: profile `technical_flatten`, flatten preview, confirm.
16. BOM stale/drift: danh sách stale, refresh preview, UoM conversion factor.
17. BOM proposals: proposal từ C/O, approve/reject/withdraw, audit trail.
18. Upload audit log: xem lịch sử file đã upload theo module.
19. Background jobs: job list/detail cho tác vụ dài như embedding/substitute refresh.
20. Admin: user, role, client staff, declaration types, client type presets, UoM standards.
21. Integration: SSO/JWT, `/v1/hub/*` API cho C/O và BCQT.
22. Chat agent: hỏi đáp theo dữ liệu client nếu bật agent.

### C/O sau Data Hub

1. Chọn client và kiểm tra dữ liệu nguồn đã đồng bộ từ Data Hub.
2. Tạo C/O case từ invoice hoặc TKX.
3. Chọn form/market, xem PSR/guidance.
4. Mở bảng kê xuất xứ theo sản phẩm, lấy BOM/Data Hub BCCT.
5. Stock allocation theo thứ tự sheet, dùng BCCT nhập từ Data Hub.
6. Substitute material: lấy gợi ý từ Data Hub, kiểm tra tồn nhập, apply substitute.
7. Submit BOM proposal ngược về Data Hub.
8. Upload supporting documents.
9. Review TKX/TKN completeness.
10. Export dossier workbook/ZIP.

## Kịch bản demo Data Hub

### 1. Mở hệ thống

1. Truy cập `http://127.0.0.1:8754`.
2. Đăng nhập `admin@data-hub.local / admin123`.
3. Mở `/clients`.
4. Chọn `Demo Precision Manufacturing VN`.

Điểm nói: Data Hub là master-data app. C/O và BCQT không tự ghi Danh Mục/BCCT/BOM trực tiếp vào database của Data Hub; họ đọc qua API hoặc gửi proposal.

### 2. Cấu hình công ty

Route:

- `/clients/demo-precision-manufactu-68f7`
- `/clients/demo-precision-manufactu-68f7/edit`
- `/clients/demo-precision-manufactu-68f7/declaration-config`

Demo:

1. Mở workspace, giới thiệu các module.
2. Mở edit client, chỉ ra `code_resolution_mode=identity`, `bom_proposal_mode=auto`.
3. Mở declaration config.
4. Chỉ ra import declaration types: `E11,E31`.
5. Chỉ ra export declaration types: `E62,B11`.

Use case: agency có thể cấu hình từng DNCX khác nhau. C/O/BCQT dùng config này để biết loại hình nào là nhập đủ điều kiện và xuất liên quan.

### 3. Upload Danh Mục

Route:

- `/clients/demo-precision-manufactu-68f7/catalog`
- `/clients/demo-precision-manufactu-68f7/catalog/upload`

File: `.ai/features/2026-05-04-demo-company-feed/input/demo_catalog_50_codes.xlsx`

Demo trên công ty mới hoặc công ty demo reset:

1. Vào Danh Mục.
2. Bấm Upload.
3. Chọn file Danh Mục.
4. Tick HQ registered.
5. Nếu vào mapping page, kiểm tra mapping:
   - `Mã HQ` -> customs/material code
   - `Mã NB` -> internal code
   - `Tên hàng` -> name
   - `Loại` -> category
   - `ĐVT` -> uom
   - `Mã HS` -> hs code
   - `Trạng thái` -> status
6. Xem preview: 50 row mới.
7. Confirm.
8. Quay lại list, filter `nvl`, `tp`, mở detail một mã.

Use case cần nói:

- Danh Mục là danh sách agency xác nhận, không phải auto-fill bừa từ BCCT.
- Mã có provenance (`client_declared`, `bcct_observed`, `bom_observed`).
- Dữ liệu Danh Mục dùng cho BOM flatten, C/O substitute, BCQT settlement.

### 4. Mã chờ duyệt

Route:

- `/clients/demo-precision-manufactu-68f7/catalog/candidates`

Demo:

1. Mở feed Mã chờ duyệt.
2. Giải thích nguồn phát hiện: BCCT, BOM, BQD.
3. Mở detail một candidate nếu có.
4. Nói quy trình accept/reject.

Use case: khi agency upload BCCT/BOM trước hoặc phát sinh mã mới, Data Hub gợi ý nhưng nhân sự vẫn quyết định mã nào được vào catalog chính.

### 5. Upload BQD

Route:

- `/clients/demo-precision-manufactu-68f7/bqd`
- `/clients/demo-precision-manufactu-68f7/bqd/upload`

File: `.ai/features/2026-05-04-demo-company-feed/input/demo_bqd_identity_50_codes.xlsx`

Demo:

1. Mở BQD.
2. Upload file BQD.
3. Kiểm tra mapping `Mã nội bộ`, `Mã HQ`, `Loại`, `Ghi chú`.
4. Preview 50 mapping.
5. Confirm.
6. Thêm thử một mapping manual nếu cần demo thao tác tay.

Use case: BQD giải quyết khách có hai hệ mã: mã HQ trên tờ khai và mã nội bộ trong BOM/ERP.

### 6. Upload BCCT

Route:

- `/clients/demo-precision-manufactu-68f7/bcct`
- `/clients/demo-precision-manufactu-68f7/bcct/upload`

File: `.ai/features/2026-05-04-demo-company-feed/input/demo_bcct_1000_rows.xlsx`

Demo:

1. Mở BCCT.
2. Upload file BCCT.
3. Kiểm tra mapping cột bắt buộc:
   - `Số tờ khai`
   - `Ngày đăng ký`
   - `Mã HQ`
4. Kiểm tra các cột bổ sung cho C/O:
   - invoice, partner, incoterms, weight, package, destination, transport, exchange rate.
5. Preview: 1.000 dòng.
6. Confirm.
7. Trên list:
   - filter direction import/export
   - search `NVL-001` hoặc `TP-001`
   - sort theo ngày hoặc mã
   - mở history một dòng nếu có link.

Use case:

- BCCT là nguồn nhập/xuất chính cho C/O stock và BCQT settlement.
- Import rows là đầu vào tồn NVL; export rows là shipment TP.
- Preview giúp tránh ghi nhầm file hoặc ghi đè không kiểm soát.

### 7. Hồ sơ tờ khai

Route:

- `/clients/demo-precision-manufactu-68f7/declarations`

Demo:

1. Mở danh sách declarations.
2. Filter missing file nếu có.
3. Mở detail một tờ khai.
4. Upload file gốc PDF/XLS/XLSX nếu có file mẫu.

Use case: Data Hub lưu record BCCT có cấu trúc và file chứng từ gốc để C/O/BCQT tra cứu lại.

### 8. Upload BOM và flatten

Route:

- `/clients/demo-precision-manufactu-68f7/bom`
- `/clients/demo-precision-manufactu-68f7/bom/upload`

File: `.ai/features/2026-05-04-demo-company-feed/input/demo_bom_multilevel_technical.xlsx`

Profile: `technical_flatten`

Demo:

1. Mở BOM.
2. Upload file BOM.
3. Chọn profile `technical_flatten`.
4. Nếu có mapping page, kiểm tra:
   - `Mã SP`
   - `Mã NVL`
   - `Định mức`
   - `ĐVT`
   - `Mã BOM`
   - `Phiên bản BOM`
5. Xem flatten preview.
6. Confirm.
7. Quay lại list BOM.
8. Mở `TP-001`.
9. Mở artifact detail, giải thích:
   - source kind
   - flatten status
   - artifact number
   - rows
   - lineage / parent

Use case:

- Technical BOM đa cấp không luôn phù hợp để tính C/O/BCQT trực tiếp.
- Data Hub lưu raw/artifact và tạo bản flatten để downstream dùng ổn định.
- Nếu UoM hoặc catalog đổi, artifact có thể stale và cần refresh có kiểm soát.

### 9. UoM drift và refresh BOM

Route:

- `/clients/demo-precision-manufactu-68f7/bom/stale`
- `/clients/demo-precision-manufactu-68f7/bom/artifact/<artifact_id>/refresh/preview`
- `/clients/demo-precision-manufactu-68f7/uom-factors`
- `/admin/uom`

Demo nếu có artifact stale/drift:

1. Mở BOM stale.
2. Mở refresh preview.
3. Chỉ ra conversion plan: source UoM, target UoM, factor, source, status.
4. Nếu thiếu factor, mở UoM factor admin/client factor để bổ sung.
5. Confirm refresh.

Use case: hệ thống không âm thầm đổi đơn vị. Nhân sự phải thấy và xác nhận conversion plan khi có rủi ro.

### 10. Substitute NVL

Route:

- `/clients/demo-precision-manufactu-68f7/catalog/<material_code>/detail`
- `/clients/demo-precision-manufactu-68f7/substitutes/refresh`
- `/admin/settings/embedding`
- `/clients/demo-precision-manufactu-68f7/jobs`

Demo:

1. Mở detail một NVL, ví dụ `NVL-001`.
2. Xem substitute panel.
3. Nếu chưa có gợi ý, nói pipeline refresh substitutes chạy bằng embedding/trigram/manual source.
4. Mở Jobs để xem tác vụ nền.

Use case: C/O cần tìm vật tư thay thế khi một NVL không đủ tồn hoặc không đạt tiêu chí xuất xứ.

### 11. Upload audit log và jobs

Route:

- `/clients/demo-precision-manufactu-68f7/uploads`
- `/clients/demo-precision-manufactu-68f7/jobs`

Demo:

1. Mở upload audit.
2. Filter theo module: catalog, bqd, bcct, bom.
3. Mở jobs list/detail.

Use case: có thể truy lại ai upload file gì, lúc nào, kết quả ingest ra sao.

### 12. BOM proposals từ C/O

Route:

- `/clients/demo-precision-manufactu-68f7/proposals`

Demo:

1. Mở proposals list.
2. Giải thích proposal lifecycle: pending, approved, rejected, withdrawn.
3. Mở detail nếu có proposal.

Use case: C/O không trực tiếp sửa BOM canonical. C/O gửi proposal; Data Hub quyết định approve/reject và giữ audit trail.

### 13. Admin và phân quyền

Route:

- `/admin/users`
- `/clients/demo-precision-manufactu-68f7/staff`
- `/admin/declaration-types`
- `/admin/client-type-presets`
- `/admin/uom`
- `/admin/settings/technical`
- `/admin/settings/embedding`

Demo:

1. User/role: dev, admin, manager, staff.
2. Client staff: cấp quyền theo client.
3. Declaration types/presets: cấu hình chuẩn cho nhóm DNCX.
4. UoM standards: canonical units và aliases.
5. Technical settings: LLM/parser/agent.
6. Embedding settings: provider/API key/model.

Use case: triển khai agency nhiều DNCX cần quản trị quyền, chuẩn đơn vị, loại hình và tích hợp.

### 14. API/SSO cho sister apps

Docs: `docs/API_CONTRACT.md`

Demo bằng trình duyệt hoặc curl nếu cần:

```bash
curl -H "Authorization: Bearer dev" \
  "http://127.0.0.1:8754/v1/hub/materials?client_id=demo-precision-manufactu-68f7&limit=5"
```

Nên nhấn mạnh:

- C/O/BCQT gọi `/v1/hub/*`.
- External consumers không connect trực tiếp vào Postgres `hub`.
- SSO dùng `/v1/auth/*`, JWKS để verify token.

## Tình huống nhập liệu phụ

Sau khi hoàn thành luồng demo chính, dùng các file dưới `docs/training/input-scenarios/` để demo thêm những case người dùng hay gặp.

| Tình huống | File | Module | Điểm cần nói |
|---|---|---|---|
| Danh Mục chuẩn tiếng Việt | `01_catalog_vi_hq_registered.xlsx` | Catalog | Happy path, tick HQ registered, preview 5 dòng |
| Danh Mục header tiếng Anh | `02_catalog_english_headers.xlsx` | Catalog | Parser/mapping linh hoạt với tên cột khác chuẩn |
| Danh Mục có dòng thiếu mã | `03_catalog_with_skipped_rows.xlsx` | Catalog | Preview hiển thị skipped row, không ingest dòng thiếu identifier |
| BQD identity | `04_bqd_identity.xlsx` | BQD | Client một hệ mã vẫn có thể upload mapping identity |
| BQD 1-N | `05_bqd_dual_code_one_to_many.xlsx` | BQD | Một mã nội bộ có thể map nhiều mã HQ, cần giải thích chính sách xử lý |
| BCCT đủ trường C/O | `06_bcct_full_co_fields.xlsx` | BCCT | Invoice, đối tác, incoterms, package, transport, exchange rate đi sang C/O |
| BCCT header dòng 5 | `07_bcct_header_row_5.xlsx` | BCCT | File có tiêu đề phía trên vẫn parse được |
| BCCT baseline update | `08_bcct_update_baseline.xlsx` | BCCT | Upload trước để tạo dữ liệu nền |
| BCCT changed update | `09_bcct_update_changed.xlsx` | BCCT | Upload sau baseline để thấy changed/noop/new/orphan preview |
| Upload nhầm module | `10_wrong_file_bom_uploaded_as_bcct.xlsx` | BCCT | BOM upload vào BCCT bị chặn, tránh ingest rác |
| BOM manual flat | `11_bom_manual_flat.xlsx` | BOM | BOM đã phẳng, profile `manual_flat` |
| BOM technical multilevel | `12_bom_technical_multilevel.xlsx` | BOM | BOM có BTP trung gian, profile `technical_flatten` |
| BOM SAP exploded | `13_bom_sap_style_english.xlsx` | BOM | SAP-style `Level`, `Component number`, `Comp. Qty`; profile `sap_exploded_levels` hoặc `auto` |

Gợi ý chọn nhanh cho buổi training 30-45 phút:

1. `03_catalog_with_skipped_rows.xlsx` để demo preview bảo vệ dữ liệu.
2. `07_bcct_header_row_5.xlsx` để demo file thực tế có nhiều dòng tiêu đề.
3. `08_bcct_update_baseline.xlsx` rồi `09_bcct_update_changed.xlsx` để demo update diff.
4. `10_wrong_file_bom_uploaded_as_bcct.xlsx` để demo hệ thống không nuốt nhầm file.
5. `12_bom_technical_multilevel.xlsx` để demo flatten BOM kỹ thuật.

## Tạo lại demo từ đầu

### Cách nhanh

Script canonical:

```bash
uv run python scripts/feed_demo_company.py --generate-only
uv run python scripts/feed_demo_company.py
```

Kết quả:

- Tạo file Excel dưới `.ai/features/2026-05-04-demo-company-feed/input/`
- Tạo công ty demo qua UI
- Upload Catalog, BQD, BCCT, BOM
- Chụp screenshot vào từng thư mục feature
- Ghi manifest vào `.ai/features/2026-05-04-demo-company-feed/manifest.json`

### Cách tạo thủ công

1. Tạo client mới:
   - Name: `Demo Precision Manufacturing VN`
   - Tax code: `0312345678`
   - Code resolution mode: `identity`
   - BOM proposal mode: `auto`
   - Tolerance: `3.0`
2. Cấu hình declaration types:
   - Import: `E11,E31`
   - Export: `E62,B11`
   - Fiscal year start month: `1`
3. Upload Danh Mục, tick HQ registered.
4. Upload BQD.
5. Upload BCCT.
6. Upload BOM với profile `technical_flatten`.
7. Kiểm tra readiness:
   - Catalog = 50
   - BQD = 50
   - BCCT = 1.000
   - BOM flattened products >= 15
   - unresolved nodes = 0

## Kịch bản C/O sau Data Hub

1. Mở C/O app và chọn cùng client.
2. Kiểm tra source readiness: catalog, BOM, BCCT, CO stock.
3. Tạo C/O case từ invoice/TKX.
4. Hệ thống match export BCCT từ Data Hub.
5. Chọn form/market, xem PSR.
6. Mở origin workbook cho `TP-001`.
7. Load BOM artifact từ Data Hub.
8. Stock allocation lấy BCCT import từ Data Hub.
9. Substitute workflow lấy candidates và stock lookup từ Data Hub.
10. Sau khi chỉnh BOM phục vụ case, submit BOM proposal về Data Hub.
11. Upload supporting docs.
12. Export dossier ZIP/workbook.

Thông điệp chính: C/O xử lý hồ sơ theo lô hàng, còn Data Hub giữ dữ liệu gốc dài hạn. Khi C/O cần thay đổi BOM, thay đổi đi qua proposal để Data Hub kiểm soát audit và tính canonical.

## Checklist trước buổi training

1. Data Hub chạy ở `http://127.0.0.1:8754`.
2. Đăng nhập được bằng admin dev account.
3. Client demo mở được: `/clients/demo-precision-manufactu-68f7`.
4. Bốn file Excel demo tồn tại trong thư mục input.
5. Manifest hiện đúng count.
6. Có ít nhất một browser tab mở Data Hub, một tab mở slide.
7. Nếu demo C/O, C/O app chạy và đã cấu hình Data Hub base URL/token.
8. Không dùng dữ liệu khách hàng thật trong slide/training nội bộ nếu chưa được phép.
