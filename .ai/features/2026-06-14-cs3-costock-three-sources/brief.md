# CS3 — Review tổng flow tồn CO: 3 nguồn ghi `co_stock_rows`

**Ngày:** 2026-06-14 · **Loại:** review/discovery (không đổi code lõi — chỉ phát hiện + quyết định) ·
**Rủi ro:** SAI TỒN nếu state lẫn lộn. Liên quan [[D1]], [[CS2]], [[CS1]].

## Ba nguồn ghi vào `co_stock_rows`

1. **Data Hub refresh** — `_refresh_co_stock_delta_or_full` (`web/co_case_context.py:2969+`) →
   `co_stock_derivation.co_stock_rows_from_bcct` → `co_stock_materializer.refresh_co_stock_for_client`
   `mode=full|delta`, **`fold=True`** (gập trừ-lùi). Route `POST /co-stock/refresh`
   (`routers/co_stock.py:387`).
2. **Workbook import (standalone)** — `co_stock_workbook.import_standard_snapshot` →
   materializer `mode=full`, **`fold=False`** (remaining đã bake). Route `/co-stock/import-snapshot`.
   Đánh dấu `payload.co_stock_source='workbook_snapshot'` (`co_stock_workbook.py:389`).
3. **CO-case claims** — `co_stock_ledger` (claim/lock/release, `FOR UPDATE` `:212`), overlay lúc đọc
   (`apply_used_qty`), recalc/Chốt từ hồ sơ.

## Phát hiện then chốt: KHÔNG có "nguồn tồn của client" tường minh

- Source-mode là **ngầm, per-row**: chỉ dòng workbook có `payload.co_stock_source='workbook_snapshot'`;
  dòng DH **không có field** này (suy ra "bcct" bằng vắng mặt).
- Guard client-level = `is_workbook_sourced()` (`co_stock_materializer.py:625`): `EXISTS` **bất kỳ 1 dòng**
  workbook → `POST /co-stock/refresh` bỏ qua (`routers/co_stock.py:400`), chặn **TOÀN BỘ** DH refresh.
- `refresh_state` (mig 011) chỉ lưu count/server_time, **không phân biệt nguồn**.
- ⇒ Không có cột `client.co_stock_source_mode`; schema **không cấm** trạng thái lẫn (vừa workbook vừa DH).

## Trả lời các câu hỏi tương tác

- **Claims khi refresh/re-import:** KHÔNG bao giờ bị xoá/sửa. Dòng có claim `locked` được giữ lại
  (`_claims_blocking_removal` `:364`), không bị DELETE → orphan-safe. Operator phải release case thì lần
  refresh sau mới dọn được. (Tốt — trực giao, không phải sửa.)
- **Re-import workbook / DH full:** REPLACE toàn bộ (`removed = old − new`, trừ dòng claim-blocked).
- **DH delta:** MERGE (removed = tombstone tường minh). Bị **force full** khi `lot_policy=aggregate`
  (`co_case_context.py:2987`).
- **Workbook-sourced gặp DH refresh:** chặn TỔNG (early-return, không partial, không override). Muốn
  quay lại DH: hiện chỉ có cách re-import (chưa có nút "chuyển sang DH").
- **Remaining math:** workbook bake `opening − used` lúc import; DH bake `bcct_qty` rồi `fold_baseline`
  trừ trừ-lùi. Cả hai trừ claim lúc đọc. **Va chạm nếu một client có cả 2 loại dòng** (cùng lô, 2 source_row
  hash khác nhau → claim trên dòng này không chặn dòng kia).

## Rủi ro / landmine

- **R1 — trạng thái lẫn (mixed):** `is_workbook_sourced` true nếu CHỈ 1 dòng workbook sót → khoá toàn bộ
  DH refresh của client; ngược lại 1 lần re-import đè hết dòng DH. Không guard schema. **SAI TỒN tiềm tàng.**
- **R2 — source_row keying:** `stock_rows_from_standard` key `(decl,line)` còn `parse_workbook` consolidate
  `(decl,line,customs_code)` (triplet). Đã verify (decl,line) unique per-lot NK2 nên chưa va, nhưng lệch khoá
  là mầm bug nếu 1 (decl,line) có 2 prefix. (Minor /rev.)
- **R3 — info-leak nhẹ:** `/co-stock/convert-workbook` `except Exception` trả raw `{exc}` cho operator
  (`routers/co_stock.py:342`). Cố ý (surface parse error) nhưng nên log full + message gọn. (Minor, operator-only.)

## Mô hình TRUNG HOÀ 3 nguồn — CHỐT 2026-06-14 (user)

Ba nguồn **sở hữu ba đại lượng KHÁC nhau**, không tranh ghi cùng field ⇒ không "đè nhau", không exclusion:

| Nguồn | Sở hữu | Ghi vào |
|---|---|---|
| DH BCCT | **opening** (số gốc hải quan) | `opening_qty` |
| Import workbook | **"còn lại" off-app** → suy `adjust = opening − còn_lại_import` (theo RULE configurable) | lớp adjust/baseline |
| CO cases | **tiêu hao** (claim/lock) | live ledger |

`tồn = opening − adjust − tiêu_hao` = `còn_lại_import − tiêu_hao` (khi có workbook). Workbook "còn lại" =
**off-app only** (user xác nhận) → CO claims trừ TIẾP, **không trừ trùng**. Khoá lô thống nhất
`(declaration_no, line_no, customs_item_code)` (gộp R2).

**Ngữ nghĩa thời điểm (user 2026-06-14):** import = **chốt baseline tại thời điểm T** (off-app tính tới T),
rồi `adjust@T` **đóng băng**; **sau T, CO là system-of-record** — mọi tiêu hao về sau do CO (claims) quản,
agency thôi dùng Excel cho lô đó. ⇒ `tồn = opening(DH, live) − adjust@T − CO_claims(sau T)`.
**Re-import = dời cutover T→T'** — và đây mới là chỗ cần **RULE adjust configurable**: xử lý xung đột nếu CO đã
claim trong khoảng T..T'. Lần import đầu (cutover) thường chưa có claim → rule chỉ thật sự kích hoạt khi re-import.

⇒ Đây chính là [[co-stock-folded-remaining-model]] hiện có, workbook = nguồn `adjust`. **Bỏ hẳn**
`is_workbook_sourced` exclusion: DH ghi opening, import ghi adjust, CO ghi tiêu hao — 3 lớp trực giao.

### Cơ chế (sau khi GỠ LEGACY 2026-06-15): một đường duy nhất

`baseline_used_qty` bake thẳng vào mỗi `co_stock_rows`, đọc-tính bằng `co_stock_ledger.apply_used_qty`
(`tồn = opening − baseline_used − live_claims`):
- **DH/BCCT refresh** → opening, **baseline_used = 0** (không còn fold).
- **Workbook import** (`/co-stock/import-snapshot`) → bake `baseline_used = opening − "còn lại"` (chốt off-app @T).
- **CO claims** → trừ lúc đọc.

**ĐÃ XOÁ HẲN (mig 017 + xoá file):** `fold_baseline`/`apply_adjustments`/`aggregate_by_lookup_key`/`refold_*`,
bảng `co_stock_adjustments`, route `/co-stock/import` overlay, `co_stock_adjustments_store.py`,
`fix_trului_unit.py`, `test_co_stock_fold.py`. ⇒ **2 bug P0 fold (CS2 §A) + va-chạm-fold của R1/R2 đều MOOT**
(không còn đường overlay). (R3 info-leak `convert-workbook` vẫn còn — minor, độc lập fold.) "adjust" = import
ghi đè `remaining` trực tiếp; re-import = re-baseline @T'.

### Còn lại (đều PARK — chưa cần)

1. **Rule re-import** (configurable): khi re-import @T' mà CO đã claim trong T..T' → reconcile thế nào
   (ghi đè remaining / cảnh báo / giữ claim). Chỉ kích hoạt khi re-import; lần đầu thường chưa có claim.
2. **DH opening cho lô MỚI trên client workbook:** hiện `is_workbook_sourced` chặn DH hoàn toàn → tờ khai
   mới sau cutover không tự về. Trung hoà đầy đủ = nới guard (DH chỉ thêm opening lô mới, không đụng remaining
   workbook). **Không cần fold_baseline.**

`/tdd` khi làm. **CS3: legacy fold đã GỠ, còn một model duy nhất (xong phần "dọn legacy").** Hai mục PARK ở trên
là phần trung-hoà-đầy-đủ (DH thêm lô mới trên client đã chốt workbook), làm khi client thật cần tờ khai mới sau cutover.
