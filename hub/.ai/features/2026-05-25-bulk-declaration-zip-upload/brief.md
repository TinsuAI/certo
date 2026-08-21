# Feature: Bulk-upload ZIP per-declaration XLS

**Status:** scoped, not implemented
**Date:** 2026-05-25
**Owner:** Data Hub
**Touches:** `app/routes/declarations.py`, `app/parsers/declaration_files.py` (reuse), `app/stores/customs_declaration_files.py` (reuse), `app/templates/clients/declaration_upload.html` (extend), new `app/uploads/declaration_zip.py` + new template `declaration_zip_preview.html`.

## Scope

UI cho phép user upload **một `.zip`** chứa file tờ khai per-declaration (TKN
hoặc TKX) cho một client cụ thể. Hệ thống:

1. Giải nén tạm vào staging dir.
2. Lọc member khớp `<prefix>_<digits>.<xls|xlsx|pdf>` (reuse
   `parsers.declaration_files.is_supported_filename`).
3. Parse + cross-validate từng file (reuse `parse_declaration_file`).
4. Render preview: tổng kết (OK / parse_error / dedup / mismatch) +
   bảng chi tiết các file non-OK.
5. User confirm → ingest qua `insert_declaration_file` với
   skip-on-error semantics. Redirect về `/clients/{id}/declarations`
   với toast summary.
6. Cancel hoặc TTL hết hạn → xoá staging dir.

Reuse hoàn toàn parser + store + FileBackend hiện có. Logic mới chỉ là:
ZIP extraction wrapper, staging persistence, preview/confirm route pair,
template mới.

### NOT in scope
- `.rar` / `.7z` / nested archives.
- ZIP trộn TKN + TKX (reject; user phải tách).
- ZIP trộn per-decl + aggregated BCCT XLS (parser khác, feature khác).
- Per-file checkbox un-select ở preview (commit là all-or-nothing-of-OK).
- OCR cho PDF (đã defer trong feature 2026-05-10).
- Background job / queue (xử lý đồng bộ trong request; cap size để giữ
  request time hợp lý).
- Multi-ZIP một request.

## Decisions

**D1. Two-step preview/confirm với staging tạm trên disk.**
- User POST `.zip` → server extract sang `/tmp/data-hub-staging/zip-<uuid>/`,
  parse tất cả, render preview. ZIP gốc xoá ngay sau extract.
- Preview HTML chứa form ẩn với `staging_id`; commit POST chỉ truyền
  `staging_id` → server đọc lại extracted files, insert lần lượt.
- TTL: staging dir > 1h → reaper xoá (trigger từ chính route khi tạo
  staging mới — không cần cron riêng cho MVP).
- Đơn giản hơn re-upload (UX tốt với ZIP lớn) và rẻ hơn DB-staged
  status (không thêm cột/state machine).

**D2. Direction explicit, không auto-detect.**
- Form dropdown như single-upload (`import` / `export`). User chọn 1
  direction áp cho toàn ZIP. Filename hint không đủ tin cậy để suy
  direction (mỗi DNCX đặt tên khác nhau).

**D3. `validate_content=True` mặc định.**
- Mirror single-upload default. Mismatch giữa filename decl_no và XLS
  content → file bị xếp vào nhóm `mismatch` ở preview, KHÔNG ingest dù
  user confirm. User phải fix tên file hoặc upload bằng route đơn lẻ
  với override.

**D4. Preview UI: summary cards + chi tiết chỉ cho non-OK (locked).**
- 4 thẻ: `OK · N`, `Duplicate · N` (đã có trong DB cùng sha256),
  `Mismatch · N`, `Parse error · N`.
- Bảng chi tiết chỉ list non-OK rows (filename, decl_no nếu có, lý do).
- OK + Duplicate gộp số, không list từng dòng — 2000+ rows làm preview
  rách trang. Không collapsible OK list ở MVP.
- Confirm CTA disabled nếu `OK + Duplicate == 0`.

**D5. Skip-on-error commit semantics.**
- Inherit từ CLI script: mỗi file độc lập, lỗi insert không abort cả batch.
- Toast cuối: "Đã thêm N file, bỏ qua D trùng, R file lỗi".

**D6. Cap kích thước (locked).**
- ZIP tải lên ≤ **256 MB** (FastAPI UploadFile spool to disk OK).
- Tổng giải nén ≤ **2 GB** (anti-zip-bomb; check `ZipInfo.file_size`
  sum trước khi extract).
- Mỗi member ≤ **10 MB** (form XLS thực tế ~500KB, 10MB là 20× buffer).
- Số member khớp pattern ≤ **5000** (Johnson TKN baseline 2351 — 2× buffer).
- Vượt ngưỡng → reject với hướng dẫn dùng CLI
  `scripts/import_declaration_archive.py`. UI bulk dành cho batch
  vừa (vài trăm file/upload); Johnson full corpus chia 2-3 ZIP hoặc
  dùng CLI.

**D7. Path traversal hardening.**
- Dùng `Path(zipinfo.filename).name` (strip dir), reject member name
  chứa `..` hoặc absolute path. Không gọi `ZipFile.extractall`.

**D8. Entry point.**
- Mở rộng `app/templates/clients/declaration_upload.html` với tabs
  "Tải 1 file" (form hiện có) + "Tải hàng loạt (ZIP)" (form mới).
- Không tạo trang riêng — giảm điều hướng cho operator.

## Risks

**R1. RAM peak với ZIP lớn nhiều file.**
- Streaming extract member-by-member giữ peak bounded ở mỗi file
  individual. Parse tuần tự. Worker còn lại trong pool 4 vẫn phục vụ.
- Mitigation: D6 cap + sequential pipeline + xoá `await file.read()`
  buffer ngay sau khi đã ghi xong tới staging dir.

**R2. Zip bomb.**
- Mitigation: D6 (kiểm `sum(zi.file_size)` trước khi extract; reject nếu
  > 2GB hoặc compression_ratio < 1/1000 ở bất kỳ member).

**R3. Path traversal / symlinks.**
- Mitigation: D7 (sanitize filename, không dùng `extractall`). zipfile
  không tạo symlink khi extract → không cần check riêng.

**R4. Staging leak nếu user abandon preview.**
- Mitigation: TTL 1h + reap-on-new-upload (mỗi request tạo staging mới
  quét `/tmp/data-hub-staging/`, xoá dir nào `mtime > 1h`).
- Backstop: tmpfs / OS cleanup khi reboot. Acceptable cho dev box +
  demo box; production nếu chạy lâu cần systemd timer.

**R5. Worker affinity cho preview→commit.**
- `--workers 4` → POST preview vào worker A, POST commit có thể vào B.
- Mitigation: staging dir nằm trên local FS shared giữa workers (single
  host). OK miễn còn cùng máy.

**R6. CSRF.**
- Xác minh middleware hiện tại có cover form POST. Nếu single-upload
  hiện đang dùng cookie auth không CSRF token, bulk cũng vậy (cùng
  threat model). Note để rev cảnh giác.

**R7. Direction mismatch sau commit.**
- User chọn direction sai → 2000 file ingest sai. Không thể batch-rollback
  trong MVP (cần CLI fix-up). Mitigation: preview hiển thị direction
  chosen banner-style, không phải input nhỏ.

## Open Questions

- **TTL 1h đủ chưa?** Operator có thể stage rồi đi họp. 1h là default;
  có thể nới lên 4h nếu phản hồi tốt từ smoke run.
- Phần còn lại đã chốt ở D4/D6.

## Manual Test Plan

1. **Happy path nhỏ** — ZIP 10 file XLS hợp lệ từ
   `data/source_inventory/johnson-vn/.../TKN/` → preview hiển thị
   "OK · 10" → confirm → 10 file vào DB, redirect về `/declarations`
   với toast "Đã thêm 10 file".
2. **Re-upload cùng ZIP** → preview "Duplicate · 10" → confirm → no-op.
3. **ZIP có 1 file đổi tên xấu** (`README.txt` + 9 XLS) → preview
   "OK · 9, ignored · 1" (file không khớp pattern bị filter ở bước
   sub-step 2, không vào parse).
4. **ZIP có 1 XLS sai khớp** (rename `00000001_107243749650.xls` thành
   `00000001_999999999999.xls`) → preview "OK · 9, Mismatch · 1" →
   confirm → 9 inserted, mismatch file không ingest.
5. **Direction mismatch** (TKX file trong ZIP user khai `import`) →
   parser không phát hiện (parser metadata-only); ingest dưới direction
   sai. Test này document hành vi để rev cảnh giác, không phải fail.
6. **ZIP rỗng / không có file khớp pattern** → preview hiển thị
   "Không tìm thấy file tờ khai trong ZIP" + cancel CTA, không có commit.
7. **ZIP > 256MB** → 400 với hướng dẫn dùng CLI.
8. **Zip bomb synthetic** (1KB ZIP expand 10GB) → reject với
   "Tổng dung lượng giải nén vượt 2GB".
9. **Path traversal synthetic** (ZIP có member `../etc/passwd`) →
   member bị reject, không nằm trong preview.
10. **Cancel** → POST cancel → staging dir xoá, redirect về
    `/declarations/upload`.
11. **TTL** — stage, đợi >1h, commit → 404 + "staging expired";
    upload mới → staging cũ bị reap.
12. **Real corpus smoke** — upload Johnson TKN ZIP thật (nếu trong cap)
    → preview render < 30s → confirm → ~2000 file vào DB, dedup chính xác
    với 16 file đã tồn tại.

## Done Criteria

- [ ] Module `app/uploads/declaration_zip.py` với pure functions
      `extract_to_staging`, `parse_staged_files`, `commit_staged_files`,
      `reap_expired_staging`. Test-first.
- [ ] 2 routes mới (preview + commit) + 1 route cancel.
- [ ] Template `declaration_upload.html` có 2 tab; new template
      `declaration_zip_preview.html`.
- [ ] Unit tests cho 4 pure functions (happy + bomb + traversal + TTL).
- [ ] Route smoke tests cho preview, commit, cancel, expire.
- [ ] `ui_smoke.py` ở feature folder + 4 screenshot:
      `01_upload_form_with_zip_tab.png`, `02_preview_with_summary.png`,
      `03_after_confirm.png`, `04_oversized_reject.png`.
- [ ] Manual test plan items 1-9 + 11 chạy thành công (item 10, 12
      optional nếu corpus thật fit cap; item 12 nếu vượt cap thì xác
      nhận hành vi rejection và document cap đề xuất nới).
- [ ] Cập nhật `.ai/STATUS.md` "Recent Changes" + push commit.

## Next step

Sẵn sàng `/tdd`:

1. Write tests cho `app/uploads/declaration_zip.py` (pure-function
   layer) — happy + bomb + traversal + TTL.
2. Implement module.
3. Wire route + template, smoke trên dev server :8754.
4. `ui_smoke.py` + screenshot.
5. `/rev` (cap 2 passes) → commit.
