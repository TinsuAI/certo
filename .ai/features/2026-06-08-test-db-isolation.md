# Feature: Cô lập DB cho test (ngừng đái vào DB dev) — discovery brief

Discovery only. Chưa code. Mở từ sự cố 2026-06-08: picker "Đổi hồ sơ" growatt có **845 hồ sơ**
toàn là fixture test (`Lock ledger`, `Workflow dossier`, `Auto code`…), tích từ 11/05→07/06. Đã
purge (xem dưới); brief này là để **ngăn tái diễn**.

## Triệu chứng → nguyên nhân gốc

- Các test **chạy có `.env`** (DB/co_stock e2e — memory [[test-env-filemode-vs-datahub]]) gọi
  endpoint thật (`POST /co-case/create`, lock sheet, export…) vào **Postgres dev dùng chung**
  (`BARRY_DATABASE_URL`, schema `co`).
- Test luôn dùng **seed client cố định** (`growatt`, `johnson-vn`) và **không dọn** case/claim/file
  tạo ra → mỗi lần chạy bồi thêm. ~4 tuần = 845 case growatt.
- Không chỉ case: cùng kiểu cruft ở `bom_*` (bom_audit_events 313, bom_uploads 102, bom_snapshots
  81…) và `source_*` — cùng cơ chế (BOM-builder + source ingestion tests ghi vào DB dev).
- File-mode (không `.env`) đỡ hơn nhờ `CO_CASE_STORE_ROOT` trỏ temp dir, nhưng vẫn tích nhẹ
  (`temp/user-test` 9, `temp/ui-runtime` 2).
- **Re-seed gotcha** (phát hiện lúc purge): `load_state` khi DB rỗng sẽ đọc fallback
  `data/local/co-cases/clients/.../cases.json` rồi ghi ngược vào DB. Muốn purge sạch phải clear
  **cả** DB **lẫn** file fallback. (đã làm; ghi nhớ cho lần sau)

## Phương án (chưa chọn)

1. **Schema throwaway mỗi lần chạy (đề xuất).** Tận dụng sẵn `database_schema()` /
   `BARRY_DATABASE_SCHEMA`: conftest autouse set schema = `co_test_<unique>`, `apply_migrations`
   vào đó, drop `cascade` ở teardown. Cô lập tuyệt đối, không đụng data dev, không cần sửa app code
   (chỉ env + fixture). `unique` lấy từ PID/worker id (không dùng random/time — xem ràng buộc dưới).
2. **DB test riêng (`TEST_DATABASE_URL`)** tách hẳn khỏi DB dev, reset đầu mỗi run. Sạch nhưng cần
   hạ tầng/CI thêm 1 DB.
3. **Cleanup fixture** xoá theo `client_id` test tạo (hoặc truncate client data) ở teardown. Đơn
   giản nhất nhưng dễ sót (claims/events/bom/source nhiều bảng — 34 bảng có `client_id`).
4. **Client id throwaway mỗi test** thay vì growatt/johnson. Giảm va chạm nhưng vẫn tích nếu không
   dọn.

Đề xuất: **PA1**. Kết hợp guard: nếu `BARRY_DATABASE_SCHEMA` không phải schema test → conftest
**từ chối chạy** test DB (chặn vô tình ghi vào `co`).

## Rủi ro / cần soi khi discover

- **Test nào phụ thuộc seed có sẵn** trong DB dev (đọc growatt/johnson row có sẵn) vs **tự tạo
  data**? PA1 cho schema trống → test kiểu "đọc seed" sẽ fail tới khi tự seed trong fixture. Phải
  liệt kê & phân loại các test chạy `.env`.
- **Migrations chạy được trên schema trống nhanh không** (845-cruft không liên quan; nhưng
  `apply_migrations` mỗi run tốn thời gian — cân nhắc cache/â template DB).
- **Ràng buộc runtime:** scripts ở đây cấm `Date.now`/random; fixture id nên từ PID/worker
  (`xdist`), không phải random.
- `bom_*` + `source_*` cũng cần cùng cô lập (cùng `database_schema`) — PA1 bao trùm vì schema chung.

## Đã làm (sự cố gốc, không phải fix này)

- Purge growatt: xoá `co_cases` 845 + `co_supporting_files` 32 + `co_case_states` blob + empty
  `cases.json` fallback. Backup: `data/local/backups/growatt-cases-purge-2026-06-08.json` (4.9MB) +
  `growatt-cases.json.bak-2026-06-08`. Giữ nguyên stock cache / client config / source / `bom_*`.
- Picker đã redesign (cap 8 + search + fix overflow) nên 800+ hồ sơ không còn phá UI — nhưng đó là
  triệu chứng, brief này nhắm gốc.

## Next step

`/discover`: liệt kê test chạy `.env` (DB-backed), phân loại tạo-vs-đọc-seed, thiết kế conftest
schema-isolation (PA1) + guard chặn ghi vào schema `co`, verify suite xanh trong schema cô lập. Cân
nhắc dọn nốt `bom_*`/`source_*` cruft growatt như một việc con.

Added: 2026-06-08.
