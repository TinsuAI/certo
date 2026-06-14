# Feature: Gỡ loạn "khoá tồn CO" + "khớp BOM" cho hệ đa-doanh-nghiệp

Discovery brief (2 trục). CHƯA code. Khởi từ câu hỏi: mỗi doanh nghiệp một hệ mã,
làm sao để phần core bớt loạn. Liên quan backlog "Review Tồn CO", memory
[[co-stock-workbook-converter]], [[co-stock-folded-remaining-model]].

## Phát hiện cốt lõi: đang TRỘN 2 trục độc lập

Sự "loạn" đến từ việc gộp 2 khái niệm khác nhau vào cùng chỗ:

- **Trục A — ĐỊNH DANH lô** (lô vật lý nào): phải company-agnostic.
- **Trục B — RECONCILE mã** (mã BOM ↔ mã tồn để khớp): per-company là hợp lý, nhưng phải dồn 1 chỗ.

`customs_item_code` (một artifact của trục B, thay đổi theo doanh nghiệp) đang bị dùng làm
1 phần KHOÁ ĐỊNH DANH (trục A) → mọi chỗ match lô phải "đoán mã" → per-company logic rò khắp nơi.

## Trục A — Định danh lô tồn CO

**Khoá tự nhiên đúng = `(declaration_no, line_no)`** (1 dòng trên 1 tờ khai = 1 lô NVL nhập).
Đã verify DUY NHẤT: growatt-vn 38287/38287, johnson-vn 60173/60173 (0 trùng). Có ở MỌI nguồn.

Hiện trạng keying (agent map):
- PK `co_stock_rows` = `(client_id, source_row)`; `source_row = import_row_id(transaction_key)`
  (`co_stock_derivation.py:29,240`) — **độc lập customs_item_code**.
- `co_stock_claims` key theo **source_row** (cấu trúc); triplet (decl,line,code) chỉ là cột audit
  (mig 010). ⇒ **Ledger/claims/lock KHÔNG bị ảnh hưởng** nếu đổi khoá overlay.
- **Trừ-lùi overlay** mới key theo TRIPLET `(decl,line,customs_item_code)`:
  `co_stock_adjustments_store.py` (`adjustment_id_for:35`, `upsert_batch`, `aggregate_by_lookup_key:299`,
  `fold_baseline:373`), `co_stock_materializer.py:refold_adjustment_lots:157`, `routers/co_stock.py:import`,
  `co_stock_events_store.py:events_for_lot:181`, unique constraint mig `008:40`.

**Quan trọng:** correctness HIỆN ĐÃ ĐẠT nhờ converter `matching_code()` phát `customs_code`= prefix "#&"
(= BCCT customs_item_code) → triplet khớp (verified converted==BCCT 2000/2000). Nên đổi khoá sang
`(decl,line)` là **đơn-giản-hoá/robust**, KHÔNG phải vá correctness:
- Bỏ giả định "#&"/đoán mã khỏi converter (matching_code biến mất → converter company-agnostic).
- Phủ luôn 43 dòng Growatt không có "#&" (fallback hiện sai) + lỗ P0-1 aggregate.

## Trục B — Khớp BOM ↔ tồn (allocation_code)

Cơ chế khớp (agent trace): pool tồn index theo `[material_code, allocation_code, customs_item_code]`
(`co_case_context.py:1600`); BOM line lookup bằng `material_code` (mã BOM) → exact-match vào pool
(`origin_material_from_bom_row:1943`). Reconcile per-company nằm ĐÚNG MỘT chỗ:
`client_config_store.resolve_allocation_code` (strategy `same_as_customs_code | description_regex |
manual_review`), áp 1 lần lúc materialize (`co_stock_derivation.py:39`). **Kiến trúc trục B đã đúng**
(docs/co-stock-architecture.md:75-82) — không cần thêm tầng mapping; thiếu thì thêm `strategy` mới.

**NHƯNG có BUG CẤU HÌNH/DATA (không phải kiến trúc):**
- growatt-vn prod materialize 38287/38287 bằng `same_as_customs_code` → `allocation_code = customs_item_code
  = category "DIOT"`. BOM Growatt dùng mã chấm `940.x/008.x` (trong ngoặc tên hàng). ⇒ **BOM Growatt
  KHÔNG khớp pool growatt-vn** (key toàn category). Đúng ra growatt phải `description_regex` (trích mã
  chấm trong ngoặc) — config 2 biến thể lệch (`growatt`=description_regex vs `growatt-vn`=same_as_customs_code).
- Johnson `same_as_customs_code` ĐÚNG (mã thống nhất: BCCT item_code = BOM material_code).
- Nghi: triệu chứng "NVL không tồn" trên sheet growatt có thể là hệ quả. CẦN xác nhận live.

## Scope

**Trong phạm vi (đề xuất):**
1. Trục B (ƯU TIÊN, nhỏ, rủi ro thấp): sửa config growatt-vn → `description_regex`, re-materialize,
   verify BOM match (allocation_code = mã chấm). Hợp nhất 2 biến thể config `growatt`/`growatt-vn`.
2. Trục A (lớn hơn, tuỳ chọn): đổi khoá overlay trừ-lùi `(decl,line,code)` → `(decl,line)`; customs_item_code
   thành thuộc tính. Converter bỏ `matching_code`.

**Ngoài phạm vi:** gỡ fold nhúng (đã có mục riêng "Review Tồn CO"); model many-to-many mã toàn cục.

## Decisions (đề xuất, chờ chốt)

- Định danh lô = `(decl, line)`; mọi mã = thuộc tính. Reconcile mã chỉ ở `resolve_allocation_code`.
- Trục B fix trước (config) vì rủi ro thấp + đang lệch thật; trục A sau (cần parity test).

## Blast radius — Trục A (đổi khoá overlay sang (decl,line))

- Schema: `co_stock_adjustments` unique `(client,decl,line,code)` → `(client,decl,line)` + index (mig mới);
  giữ cột customs_code làm audit. Migration dọn trùng `(decl,line)` khác code (consolidate).
- Code: `adjustment_id_for`, `upsert_batch`, `aggregate_by_lookup_key`, `fold_baseline`,
  `refold_adjustment_lots`, `routers/co_stock.py:import` keys, `events_for_lot` (bỏ tham số code).
- KHÔNG đụng: `record_sheet_lock/release`, `apply_used_qty`, `used_qty_by_lot` (đều theo source_row).
- Aggregate policy: `(decl,line)` đơn phải map vào lô gộp (line_no comma-join) → containment, không equality
  (cùng vùng bug P0-1). 2 client hiện tại = line_level nên khớp thẳng.

## Risks

- **SAI TỒN** nếu overlay match sai sau đổi khoá → BẮT BUỘC parity test trước.
- Trùng `(decl,line)` nhiều customs_code trong adjustments cũ → cần audit + consolidate khi migrate.
- Re-materialize growatt-vn (trục B) đổi allocation_code hàng loạt → kiểm tra không vỡ claims đang lock
  (claims theo source_row nên an toàn, nhưng allocation_code đổi ảnh hưởng khớp BOM hiện có).
- Demo tests fail nếu chạy với .env [[test-env-filemode-vs-datahub]].

## Parity-test plan (trước khi đổi)

- **Trục B:** snapshot growatt-vn co_stock_rows (allocation_code) trước/sau khi đổi config+re-materialize;
  assert allocation_code chuyển category→mã chấm; chạy 1 origin sheet growatt thật, đếm NVL khớp tồn
  trước/sau (kỳ vọng tăng). file-mode fixture cho resolve_allocation_code description_regex.
- **Trục A:** golden test: cùng workbook trừ-lùi → import (triplet) vs import (decl,line) → `remaining_qty`
  mỗi (decl,line) phải GIỐNG HỆT trên data thật (growatt + johnson, DB). file-mode unit cho
  aggregate_by_lookup_key/(fold_baseline) theo khoá mới + case aggregate containment.

## Open Questions

1. ~~growatt-vn có đang thực sự "NVL không tồn"?~~ ✅ **XÁC NHẬN LIVE: CÓ, lệch nặng.** 335 mã BOM
   Growatt thật khớp pool tồn growatt-vn hiện tại chỉ **16/335 = 4%**; nếu dùng `description_regex`
   (trích mã chấm trong ngoặc) thì **335/335 = 100%**. growatt-vn = 631 category-key cho 3108 mã chấm
   thật ⇒ 96% NVL không khớp tồn (và 4% "khớp" có thể khớp nhầm bucket category). Trục B = bug LIVE.
2. 2 biến thể config `growatt` vs `growatt-vn` — cái nào authoritative cho prod? Hợp nhất ở đâu (DH client_config?).
3. Trục A có đáng làm ngay không, hay chỉ cần Trục B + giữ converter matching_code (correctness đã đủ)?
4. Khi đổi khoá (decl,line): cột customs_code trong adjustments/events giữ làm audit hay bỏ?

## Status

- **Trục B — FIXED trên DEV (2026-06-14).** `growatt-vn` config `strategy: same_as_customs_code →
  description_regex` (`save_client_config`, version 2; backup `config.json.bak-2026-06-14`). Re-materialize
  allocation_code in-place 38287 dòng từ payload (CHỈ allocation_code/material_code — KHÔNG đụng qty).
  Kết quả: **BOM khớp 4% → 99%** (16/335 → 334/335); allocation_code: category → mã chấm; qty nguyên vẹn,
  0 dòng remaining NULL. Còn lại: 3452 fallback (description không có ngoặc) + 38 rỗng = đuôi data, ra
  `requires_review`, không phải lỗi wiring.
- **TODO PROD:** prod growatt-vn nhiều khả năng cùng misconfig. Cần: (1) verify config prod; (2) đổi
  strategy → description_regex; (3) **FULL refresh** (delta KHÔNG re-derive allocation_code của dòng
  BCCT không đổi) — hoặc chạy lại script re-materialize in-place. Xác minh prod config là CO-local hay DH.
- **Trục A — chưa làm** (không khẩn; converter đã bridge đúng). Cần `/tdd` + parity test khi làm.

## Next step

Trục B done-dev. Quyết: (a) đẩy Trục B lên prod khi sẵn sàng; (b) Trục A để sau (tùy chọn, dọn-cho-sạch).
