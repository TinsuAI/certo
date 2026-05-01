# Manual test guide — 2026-05-04 BCCT overhaul + LLM smart parser

Mỗi file → upload vào ĐÂU và phải thấy CÁI GÌ.

## 0. Setup

```bash
# Server (nếu chưa chạy)
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload

# Login: http://127.0.0.1:8754/login
#   email:    admin@data-hub.local
#   password: admin123
#   role:     dev (cần để vào /admin/settings/technical)

# Reset state để chạy lại từ đầu
psql -d data_hub -f data/manual_test/_cleanup.sql
```

Tất cả test dùng client **Growatt VN** (`growatt-vn`).

---

## File 01 — `01_stage_AB_full_co_bcct.xlsx`

### Upload vào đâu

```
http://127.0.0.1:8754/clients/growatt-vn/bcct/upload
```

Bấm "Choose File" → chọn `01_stage_AB_full_co_bcct.xlsx` → "Tải lên & xử lý".

### Phải thấy cái gì

1. Form upload **không có ô "Năm"** (year đã bỏ; derive từ Ngày đăng ký).
2. Sau khi submit → redirect về `/clients/growatt-vn/bcct?ingested=3&new=3&...`
3. **Banner xanh ở đầu trang:** `✓ Đã ingest 3 dòng (3 mới).`
4. Bảng BCCT có 3 dòng mới với decl_no `MAN_AB_001`, `MAN_AB_002`, `MAN_AB_003`.

### Verify 12 typed CO columns ngấm xuống DB

```bash
curl -H "Authorization: Bearer x" \
  "http://127.0.0.1:8754/v1/hub/bcct?client_id=growatt-vn&declaration_no=MAN_AB_001" \
  | python3 -m json.tool | head -40
```

Field mong đợi: `exporter_name='CÔNG TY TNHH GROWATT NEW ENERGY VIETNAM'`,
`consignee_name='ACME ENERGY GMBH'`, `incoterms='FOB'`, `weight=245.5`,
`weight_unit='KGM'`, `package_count=8`, `invoice_date='2026-03-10'`,
`departure_date='2026-03-16'`, `destination_code='DEHAM'`,
`transport_mode='1'`, `exchange_rate=25400`, `year=2026` (computed from
`registration_date` 2026-03-15).

---

## File 02 — `02_stage_D_chinese_headers.xlsx`

### Test 2a (ưu tiên): LLM CHƯA cấu hình → thông báo rõ

```bash
# Đảm bảo LLM tắt:
psql -d data_hub -c "update hub.app_settings set value='' where key in ('llm_base_url','llm_model','llm_api_key');"
```

Upload vào:

```
http://127.0.0.1:8754/clients/growatt-vn/bcct/upload
```

→ Phải nhận **HTTP 400** với JSON:

```
File không khớp parser tự động: No BCCT rows recognized; check headers
(Số tờ khai / Mã NPL+SP).. Bật LLM Smart Parser ở
/admin/settings/technical hoặc upload file đúng format BCCT.
```

### Test 2b: LLM ĐÃ cấu hình đúng → hiển thị propose UI

Vào `/admin/settings/technical`, điền (chú ý đúng FIELD):

```
Base URL:                       https://api.anthropic.com/v1
                                  hoặc https://api.openai.com/v1
                                  hoặc http://192.168.1.88:2455/v1  (LAN)
Model:                          claude-sonnet-4-6
                                  hoặc gpt-4o-mini
                                  ↑ ĐỪNG paste email vào đây
API Key:                        sk-ant-... hoặc sk-...
Temperature:                    0.0
Timeout (s):                    30
Max calls / day / client:       50
```

→ "Lưu" → toast "Đã lưu cài đặt".

Upload `02_stage_D_chinese_headers.xlsx` → redirect:

```
/clients/growatt-vn/bcct/parse-mapping/{upload_id}
```

→ Bảng review từng cột với LLM đề xuất:

```
Header in file       Logical field        Sample
报关单号              declaration_no       MAN_D_001 · MAN_D_002
项次                 line_no              1 · 1
申报类型              declaration_type     E42 · E42
登记日期              registration_date    2026-04-01 · 2026-04-05
海关编码              customs_code         ZH-INV-3000 · ZH-INV-5000
货物名称              goods_name           光伏逆变器 5kW Growatt · ...
…
```

→ Review, edit field bị sai, "Lưu mapping & ingest" → 2 dòng mới ngấm vào BCCT.

Upload **lần 2** cùng file → KHÔNG gọi LLM nữa (mapping đã cache, signature trùng) → ingest thẳng. Verify ở DB:

```sql
select use_count, last_used_at from hub.parser_mappings
where client_id='growatt-vn' and module='bcct';
-- use_count = 1 sau upload đầu confirm; tăng dần mỗi lần upload sau
```

### Test 2c: LLM cấu hình SAI → thông báo rõ là LLM lỗi (không phải parser)

Để Base URL đúng nhưng Model nhầm (ví dụ paste email như lỗi của ông) → upload → nhận:

```
Parser cứng từ chối + LLM gọi không thành công (LLMProposalError).
Kiểm tra cấu hình tại /admin/settings/technical (base_url, model,
api_key) hoặc xem chi tiết tại /clients/growatt-vn/uploads.
```

→ Vào `/clients/growatt-vn/uploads` để xem `parse_error` chi tiết (không lộ key).

---

## File 03a — `03a_stage_C1_baseline.xlsx`

### Upload vào đâu

```
http://127.0.0.1:8754/clients/growatt-vn/bcct/upload
```

### Phải thấy gì

- Toast: `✓ Đã ingest 3 dòng (3 mới)`
- 3 decl_nos mới: `MAN_C1_A` (qty=100), `MAN_C1_B` (qty=200), `MAN_C1_C` (qty=300)

---

## File 03b — `03b_stage_C1_changed.xlsx` ← **trigger preview UI**

### Upload vào đâu

Sau khi đã upload 03a, upload tiếp 03b vào:

```
http://127.0.0.1:8754/clients/growatt-vn/bcct/upload
```

### Phải thấy gì

Redirect sang **preview**:

```
/clients/growatt-vn/bcct/upload/preview/{pending_id}
```

Trang hiển thị:

```
Tổng quan:
  • 1 dòng mới sẽ được thêm        (MAN_C1_D)
  • 1 dòng không đổi (skip)         (MAN_C1_B)
  • 1 dòng có thay đổi   [cần confirm]  (MAN_C1_A: qty 100→88)
  • 1 dòng mất tích       [orphan candidate]  (MAN_C1_C bị xóa khỏi file)

Thay đổi giá trị (1 dòng):
  Số TK         Dòng   Field      Hiện tại (DB)   Mới (file)
  MAN_C1_A-1    1      quantity   100.0           88.0

  [ ] Xác nhận ghi đè tất cả 1 dòng đã đổi

Dòng mất tích — orphan (1 dòng):
  Số TK         Dòng
  MAN_C1_C-1    1

  [ ] Xác nhận xóa tất cả 1 dòng orphan

[Apply confirmed changes] [Hủy]
```

### Test regression bug (post-/rev fix)

**Tick CHỈ "Xác nhận xóa orphan", KHÔNG tick "Xác nhận ghi đè"** → submit.

Verify qua psql:

```sql
select transaction_key, line_no, quantity from hub.bcct_rows
where transaction_key like 'MAN_C1%' order by transaction_key;
```

**Phải thấy:**
- `MAN_C1_A-1` qty = 100 (giữ nguyên — user không tick confirm DIFF) ←
  bug cũ sẽ là 88 hoặc bị xóa
- `MAN_C1_B-1` qty = 200 (NOOP)
- `MAN_C1_D-1` qty = 400 (NEW, đã insert)
- `MAN_C1_C-1` KHÔNG còn (đã xóa, user confirm orphan)

Toast: `✓ Đã ingest N dòng (1 mới · 1 đã xóa · 1 không đổi)` (1 đã xóa = orphan; updated=0 vì không tick).

### Idempotency

Copy URL preview, mở tab thứ 2, click submit ở cả 2 tab → tab thứ 2 nhận 404 "Pending upload not found or already applied".

---

## Stage C2 — History page (không cần file)

Sau khi xong File 03b, MAN_C1_A có 1 update event (từ file 03a) và MAN_C1_C có 1 delete event.

### Vào đâu

```
http://127.0.0.1:8754/clients/growatt-vn/bcct/history/MAN_C1_A-1/1
```

(Format: `transaction_key/line_no` — txn_key của hub là `<decl_no>-<line_no>`)

### Phải thấy gì

Bảng các sự kiện thay đổi với:
- `changed_at`: timestamp
- `changed_by`: user_id (admin của ông)
- `action`: update / delete
- Field thay đổi + giá trị cũ → mới
- `upload_id`: tham chiếu ngược file gốc

(Nếu confirm DIFF ở bước trước thì sẽ có 1 row update; nếu chỉ confirm orphan thì MAN_C1_A không có history events.)

### Ops bypass CLI

```bash
uv run python scripts/bcct_force_apply.py \
  --client growatt-vn \
  --file data/manual_test/03b_stage_C1_changed.xlsx \
  --dry-run
```

In ra NEW/NOOP/DIFF/ORPHAN counts; không apply.

Apply thật:

```bash
uv run python scripts/bcct_force_apply.py \
  --client growatt-vn \
  --file data/manual_test/03b_stage_C1_changed.xlsx \
  --confirm-orphans
```

Sau đó vào `/clients/growatt-vn/bcct/history/MAN_C1_A-1/1` → row mới nhất có `changed_by='ops:script'` (audit thấy thằng ai bypass).

---

## Reset giữa các lần test

```bash
psql -d data_hub -f data/manual_test/_cleanup.sql
```

Wipe các row `MAN_*` + history + pending + parser_mappings (Chinese headers) + audit của upload manual-test. Settings LLM không bị xóa.
