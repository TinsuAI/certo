# Kiến trúc Tồn CO (CO Stock)

> Tài liệu xương sống. Tồn CO sai lệch là hỏng toàn bộ app CO — mọi hồ sơ C/O đều
> đứng trên nó. Tài liệu này giải thích bằng logic nghiệp vụ, có neo tới code để tra cứu.
> Cập nhật: 2026-06-08 (sau audit D1, commit `2c856da`).

---

## 1. TL;DR

- **Tồn CO** = lượng nguyên vật liệu nhập khẩu **còn lại theo từng lô**, đủ điều kiện dùng cho hồ sơ C/O.
- **Nguồn sự thật bị chia đôi:** Data Hub sở hữu **BCCT thô** (sự thật tờ khai). App CO sở hữu **tồn CO**
  (đối soát trừ-lùi + sổ cái tiêu thụ + cấu hình suy diễn). Hai phần sau **không có bản sao ở Data Hub**.
- **Công thức:** `tồn còn lại = mở đầu − trừ-lùi (tĩnh) − claim (động)`.
- **Khoá nhận diện lô** = `direction ‖ số tờ khai ‖ dòng ‖ mã hàng (item_code)`. **Không** dùng mã HS.
- `co_stock_rows` là **hình chiếu tái dựng được (projection)**, KHÔNG phải nguồn sự thật. Hai bảng
  `co_stock_adjustments` + `co_stock_claims` mới là nguồn sự thật **không khôi phục được** → cần backup nghiêm nhất.

---

## 2. Tồn CO là gì

Mỗi **lô (lot)** ứng với một dòng hàng nhập trên một tờ khai hải quan: cùng một vật tư, nhập về một lần,
còn lại bao nhiêu để cấp C/O. Operator làm C/O cho lô hàng xuất → "rút" vật tư từ các lô tồn này để chứng
minh xuất xứ. Tồn phải đúng, nếu không hồ sơ chứng minh dùng vật tư **không có thật** (over-claim) hoặc bỏ
sót vật tư đang còn (under-claim).

---

## 3. Nguyên tắc sở hữu (ai sở hữu cái gì)

| Bên | Sở hữu (nguồn sự thật) | Có ở đâu |
|---|---|---|
| **Data Hub** | **Chỉ** BCCT thô — sự thật tờ khai nhập/xuất | bảng `bcct_*` phía Data Hub |
| **App CO** | **Trừ-lùi** (đối soát ngoài app) | `co_stock_adjustments` (DB CO) |
| **App CO** | **Sổ cái claim** (tiêu thụ xuyên hồ sơ) | `co_stock_claims` (DB CO) |
| **App CO** | **Cấu hình suy diễn** (đủ điều kiện, ánh xạ mã, chính sách gộp lô) | client_config (Data Hub cấp config, CO áp dụng) |

**Đã xác minh trong code:** `co_stock_ledger.py` và `co_stock_adjustments_store.py` **không hề** gọi Data Hub.
Adapter Data Hub chỉ có 2 lệnh ghi-lên và **cả hai đều về BOM/định mức**, không có gì về tồn/claim/trừ-lùi.
→ Tồn CO là của app CO. Data Hub chỉ cung cấp lớp **mở đầu** (lượng nhập gốc).

### Hệ quả sống còn cho backup
- **Mất `co_stock_rows` (snapshot)** → khôi phục được: kéo lại BCCT + gấp lại từ `co_stock_adjustments`.
- **Mất `co_stock_adjustments` / `co_stock_claims`** → **KHÔNG khôi phục được** (không có upstream).
  Đây là "viên ngọc" thật sự cần bảo vệ — không phải snapshot.

---

## 4. Khoá nhận diện lô (identity)

Khoá thật của một lô, trong code là `transaction_key` (`source_workbook_io.py:495`):

```
transaction_key = direction ‖ số tờ khai ‖ dòng ‖ mã hàng (item_code)
source_row      = "import-row-" + sha1(transaction_key)[:16]    # co_stock_derivation.py:240
```

`source_row` là **khoá chính** của snapshot và là khoá mà mọi claim trỏ vào.

### Tại sao có mã hàng, không chỉ tờ khai + dòng
Mô hình BCCT **không coi (tờ khai + dòng) là duy nhất tuyệt đối** — số dòng qua đường ingest không đảm bảo
sạch, và mã hàng còn là **khoá khớp với file trừ-lùi của khách**. Thiếu mã → khớp nhầm lô → gấp trừ-lùi sai
chỗ → sai tồn.

### Mã hàng ≠ Mã HS — đừng nhầm
| | Mã hàng / NPL (`item_code`) | Mã HS (`hs_code`) |
|---|---|---|
| Là gì | Mã vật tư **khai trên dòng tờ khai** | Mã phân loại thuế quan (vd `8541.43.00`) |
| Độ mịn | Mịn — định danh đúng món | Thô — trăm vật tư chung 1 mã |
| Trong identity? | ✅ Có | ❌ Không (chỉ là thuộc tính mô tả) |

Lấy mã HS làm identity là vô dụng (cái rổ chung không phân biệt được lô).

### Ba thứ dễ lẫn
- **`item_code`** — mã hàng *khai trên tờ khai*. **Trong identity, bất biến.** Với Johnson = mã NVL nội bộ.
- **`allocation_code`** — mã NVL *chuẩn hoá, CO suy ra* qua cấu hình ánh xạ. **Thuộc tính, đổi được.**
  (Johnson trùng `item_code` vì cấu hình `same_as_customs_code`.)
- **`hs_code`** — mã HS thuế quan. **Thuộc tính mô tả.**

> Identity phải đứng trên sự thật bất biến (`item_code` khai báo), KHÔNG trên mã suy-ra (`allocation_code`):
> sửa lại bảng ánh xạ không được phép làm "dịch chuyển" lô → mồ côi claim, lệch trừ-lùi.

---

## 5. Công thức tồn = 3 tầng

```
tồn còn lại của 1 lô = opening − baseline − claims
                        (mở đầu)  (trừ-lùi)  (khoá động)
```

| Tầng | Là gì | Nguồn | Tính khi nào |
|---|---|---|---|
| **1. opening** | Lượng nhập gốc của lô (hoặc số ghi đè tay) | BCCT (`quantity`) hoặc `opening_qty_override` | Lúc dựng/refresh |
| **2. baseline (trừ-lùi)** | Lượng khách **đã xuất CO ngoài app** | `co_stock_adjustments.used_qty` | Gấp sẵn vào snapshot |
| **3. claims (khoá)** | Lượng các hồ sơ C/O **khác trong app** đang giữ chỗ | `co_stock_claims` (locked) | Phủ lên **lúc đọc** |

Hai tầng đầu **tĩnh** → gấp cứng vào snapshot (re-tính mỗi refresh). Tầng ba **động** → cộng/trừ tươi mỗi
lần đọc. Thiết kế đúng: tĩnh thì cache, động thì tính tươi.

---

## 6. Lưu trữ (4 bảng)

| Bảng | Vai trò | Khoá | Sở hữu |
|---|---|---|---|
| `co_stock_rows` | **Snapshot tồn** (projection đọc-nhanh) | `(client_id, source_row)` | Tái dựng được |
| `co_stock_claims` | **Sổ cái claim** (lock/release xuyên hồ sơ) | `claim_id` | **Nguồn sự thật** |
| `co_stock_adjustments` | **Trừ-lùi** (override mở đầu + đã xuất) | `(client_id, decl, line, customs_code)` | **Nguồn sự thật** |
| `co_stock_refresh_state` | Sổ ghi mốc refresh (delta/full) | `client_id` | Phụ trợ |

`co_stock_rows.remaining_qty` lưu giá trị **đã gấp** = `opening − baseline` (CÓ DẤU, âm được nếu trừ-lùi quá tay).

---

## 7. Vòng đời

### A. DỰNG (lần đầu / từ rỗng)
1. Kéo **toàn bộ** dòng nhập BCCT từ Data Hub.
2. **Biến đổi từng dòng** thành lô: lọc theo loại tờ khai được phép (`eligible_import_declaration_types`),
   ánh xạ mã hàng → `allocation_code`, xác định đủ/không đủ điều kiện. Chính sách gộp lô (`lot_policy`):
   - **`line_level`** (johnson + growatt): 1 dòng tờ khai = 1 lô. `source_row` = 1 id. **1-1.**
   - **`aggregate_by_declaration_and_allocation_code`**: gộp nhiều dòng cùng tờ khai + cùng `allocation_code`
     → 1 lô; `source_row` = **danh sách id nối dấu phẩy** (`co_stock_derivation.py:180`).
3. **Gấp tầng trừ-lùi** vào (mục D).
4. **Ghi cứng** vào `co_stock_rows`.

### B. CẬP NHẬT (refresh từ Data Hub) — phần rủi ro nhất
Hai chế độ, chọn ở `_refresh_co_stock_delta_or_full` (`co_case_context.py`):

- **FULL** — kéo lại tất cả; `removed = cũ − mới` (dòng không còn trong nguồn → xoá). **Tự chữa lành.**
- **DELTA** — chỉ kéo *thay đổi từ mốc trước* + danh sách "đã xoá" (tombstone). Nhanh nhưng **mong manh**.

**Điều kiện đi DELTA (đủ cả 4):** chính sách `line_level` **VÀ** snapshot không rỗng **VÀ** có mốc
`last_bcct_server_time` **VÀ** Data Hub hỗ trợ envelope. Thiếu bất kỳ → FULL.

**Hợp đồng Data Hub** (`.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`):
- `since` là **loại trừ** (`indexed_at > since`).
- `server_time` là **mốc cao nhất chống khe hở** — luôn dùng `server_time` lần trước làm `since` lần sau.
- **tombstone là một-lần** (`removed_at > since`, đủ ở trang 1, **không gửi lại** ở cửa sổ sau).

**Bất biến phải giữ:** áp cùng một trạng thái upstream qua FULL và qua DELTA+tombstone → ra **cùng**
`co_stock_rows`. Hiện CHƯA có test parity cho bất biến này.

#### D1 — các lỗ đã/đang xử lý (xem `.ai/features/2026-06-08-co-stock-delta-vs-full-refresh-audit.md`)
| Mã | Lỗ | Trạng thái |
|---|---|---|
| D | Kéo FULL về **rỗng** (thành công, 0 dòng) → xoá sạch snapshot | ✅ FIXED — full + derive 0 trên snapshot>0 → **không xoá, giữ nguyên, báo lỗi** |
| B | Lấy mốc `server_time` **sau** khi kéo → dòng trong khe hở mất | ✅ FIXED — lấy mốc **trước** khi kéo; thêm probe trang-1-only (`bcct_server_time`) |
| A | Delta + chính sách **gộp lô** → tombstone không khớp (lô ma) + chèn lô trùng (nhân đôi) | ✅ FIXED (guard) — gộp lô → ép FULL |
| C | **tombstone của lô đang bị claim khoá**: tiêu thụ một lần, không gửi lại → lô ma sau khi nhả khoá | ❌ OPEN |
| E | sync-status chỉ so **số đếm dòng** → 2 tập khác nội dung cùng số lượng vẫn báo "đồng bộ" | ❌ OPEN |
| F | kết quả refresh `{ok, rows:0}` mơ hồ ("không có gì mới" vs "lỗi") | ❌ OPEN (một phần: case abort của D trả `ok:false`) |

### C. TIÊU THỤ (hồ sơ C/O dùng tồn) — tầng động
1. Operator dựng bảng kê, phân bổ lô cho từng NVL, **chốt (khoá) bảng kê** (`record_sheet_lock`).
2. Khoá → ghi **claim** vào `co_stock_claims`: mỗi claim = "hồ sơ X, bảng kê Y, giữ Z đơn vị của lô".
3. **Kiểm tra chống vượt tồn TRƯỚC khi ghi** (`co_stock_ledger.py:197-260`):
   - Khoá cứng các dòng lô (`... order by source_row for update`) để 2 hồ sơ chốt cùng lúc **xếp hàng**.
   - Kiểm: `lượng đòi ≤ (remaining_qty đã gấp − tổng claim của các hồ sơ KHÁC)`. Bất kỳ lô âm → **huỷ
     toàn bộ giao dịch, không ghi gì** (`StockOverclaimError`).
4. **Nhả khoá** (`record_sheet_release`) → xoá claim của hồ sơ → tồn trả về pool.
5. Claim **xuyên hồ sơ + tức thời**: hồ sơ A khoá làm giảm tồn hồ sơ B thấy ngay.

**Đọc-thời** (`apply_used_qty`, `co_stock_ledger.py:570`): `used = baseline + claim`;
`remaining_signed = opening − used`; hiển thị `max(0, signed)`; gắn cờ `ledger_overclaim` khi âm.

> **Phụ thuộc cấu trúc (quan trọng):** kiểm-tra-chống-vượt-tồn **bị bỏ qua nếu snapshot rỗng**
> (`co_stock_ledger.py:197-203` — tin vào kiểm-tra-lúc-tính). ⇒ tồn đúng **đòi hỏi snapshot luôn có mặt và
> tươi**. Đây là lý do lỗ D (xoá snapshot) nguy hiểm gấp đôi: vừa hiện tồn sai, vừa **tắt lá chắn**, để claim
> xấu ghi thẳng vào sổ cái không-khôi-phục-được.

### D. TRỪ-LÙI (điều chỉnh tĩnh) — tầng 2
- Khách upload file "đã xuất" cũ → mỗi lô: `opening_qty_override` (ghi đè mở đầu) + `used_qty` (đã xuất).
- **Gấp** vào snapshot lúc import và **gấp lại mỗi lần refresh** (`fold_baseline`, `co_stock_adjustments_store.py:349`).
  Ghi: `bcct_qty` (lượng gốc, giữ để hoàn tác void), `opening_qty`, `baseline_used_qty`, `remaining_qty = opening − baseline`.
- **Idempotent:** luôn tính lại `opening` từ `bcct_qty` ⇒ refresh / re-import nhiều lần **hội tụ**, không cộng dồn.
- *(Lịch sử: từng có lỗi đơn vị kg vs tấn → lệch 1000×; xử lý như lỗi dữ liệu, fold cố ý "ngu".)*

---

## 8. Bất biến cốt lõi (phải luôn đúng)

1. **Identity ổn định:** cùng một dòng BCCT → cùng `transaction_key` → cùng `source_row` qua mọi lần
   re-import. (Phụ thuộc Data Hub — xem mục 10.)
2. **Parity FULL = DELTA:** cùng trạng thái upstream, hai đường refresh ra cùng `co_stock_rows`.
3. **Không tự xoá khi nghi ngờ:** full pull rỗng trên snapshot có dữ liệu = lỗi tạm, **giữ tồn**.
4. **Mốc cao nhất không vượt data:** `server_time` ghi vào luôn ≤ data đã persist (lấy trước khi kéo).
5. **Không vượt tồn:** tổng claim active của một lô ≤ `opening − baseline`; kiểm dưới `FOR UPDATE`.
6. **Fold hội tụ:** gấp lại nhiều lần không đổi kết quả.

---

## 9. Bản đồ rủi ro

| # | Rủi ro | Trạng thái |
|---|---|---|
| 1 | Refresh kéo rỗng → xoá sạch tồn | ✅ FIXED (D) |
| 2 | Mốc thời gian → mất dòng trong khe hở | ✅ FIXED (B) |
| 3 | Delta + gộp lô → lô ma + nhân đôi | ✅ FIXED (A, guard) |
| 4 | Race 2 hồ sơ chốt cùng lúc → vượt tồn | ✅ FIXED (`FOR UPDATE`) |
| 5 | tombstone một-lần → lô ma sau nhả khoá | ❌ OPEN (C) |
| 6 | `transaction_key` đổi khi re-import → đứt liên kết toàn bộ | ⚠️ Data Hub **chưa ký xác nhận** |
| 7 | Snapshot cũ/không refresh → tồn lỗi thời + tắt lá chắn over-claim | ⚠️ Không có refresh định kỳ |
| 8 | sync-status chỉ so số đếm → che drift nội dung | ❌ OPEN (E) |
| 9 | Đơn vị trừ-lùi lệch (kg/tấn) | ⚠️ Xử lý mức dữ liệu |

---

## 10. Phụ thuộc chưa bảo chứng (rủi ro lớn nhất)

Toàn bộ mô hình đứng trên việc **Data Hub luôn cấp cùng `transaction_key` cho cùng một dòng khi re-import**.
Nếu mã này đổi (UUID ngẫu nhiên, đếm tăng dần…) thì một lần re-import trông như "mọi lô cũ bị xoá + mọi lô
mới thêm" → claim mồ côi hàng loạt, trừ-lùi khớp sai, tồn loạn. Hợp đồng
`.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md` đã **yêu cầu** Data Hub xác nhận cách dựng
`transaction_key` ổn định, nhưng **ô ký duyệt còn trống**. → Việc cần đẩy lên Data Hub xác nhận trước tiên.

---

## 11. Tham chiếu code

| Việc | File |
|---|---|
| Biến đổi BCCT → lô + gộp lô | `app/co_stock_derivation.py` |
| Khoá nhận diện (`transaction_key`) | `app/source_workbook_io.py:495` |
| Snapshot UPSERT + xoá có chủ đích + kế hoạch xoá | `app/co_stock_materializer.py` (`refresh_co_stock_for_client`, `_plan_removed_keys`) |
| Chọn delta/full + delta pull + probe mốc | `app/web/co_case_context.py` (`_refresh_co_stock_delta_or_full`, `_try_delta_refresh`, `_full_refresh`, `_probe_server_time`) |
| Probe mốc trang-1 (rẻ) | `app/data_hub_client.py` (`bcct_server_time`) |
| Sổ cái claim + chống vượt tồn + overlay đọc-thời | `app/co_stock_ledger.py` (`record_sheet_lock`, `record_sheet_release`, `apply_used_qty`) |
| Trừ-lùi: gấp + import + void | `app/co_stock_adjustments_store.py` (`fold_baseline`) |
| Schema | `db/migrations/001` (rows), `007` (claims), `008` (adjustments), `011`/`014` (refresh_state) |
| Audit D1 | `.ai/features/2026-06-08-co-stock-delta-vs-full-refresh-audit.md` |
