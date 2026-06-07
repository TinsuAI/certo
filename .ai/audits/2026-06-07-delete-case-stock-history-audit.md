# Audit — Xoá hồ sơ đang giữ tồn → nhả tồn & lịch sử tồn CO ghi nhận thế nào (2026-06-07)

Audit-only (chưa sửa code). Trả lời 3 câu hỏi backlog: khi xoá một case đang giữ claim,
(1) tồn có thực sự được nhả không, (2) lịch sử/ledger ghi nhận ra sao, (3) còn truy được hồ
sơ nào từng giữ lot đó không sau khi case biến mất — và đánh giá có hợp lý không.

> **Đính chính (2026-06-07, sau khi đọc mig 016):** Bản đầu nói `co_stock_claims` **không** có
> FK và **sống sót** qua xoá case — SAI. `co_stock_claims` có FK `ON DELETE CASCADE` tới
> `co_cases` (`db/migrations/016_co_stock_claims_case_fk.sql`), nên dòng claim (đã `released`) bị
> **prune** khi xoá case row. **Chỉ `co_stock_events` (append-only, không FK) sống sót.** Điều này
> *củng cố* GAP A/B (events là dấu vết DUY NHẤT) và giải thích vì sao bước release-trước là để
> ghi **event** (vì claim row đằng nào cũng bị cascade xoá). Các phần dưới đã sửa theo.
> (Block-reason cũng đã bỏ nhánh `origin_calculation_lock` — mutex A xoá ở Phase 1 cùng ngày.)

## Kiến trúc 2 tầng (đã đọc code)

- **`co_stock_claims`** (mig `007`) — ledger SỐNG. Mỗi claim `status in ('locked','released')`.
  Tồn còn lại = BCCT available − **chỉ** tổng claim `status='locked'` (`used_qty_by_lot`,
  `co_stock_ledger.py:464`). **Có FK `(client_id, case_id)` → `co_cases` `ON DELETE CASCADE`**
  (mig `016`): xoá case row → claim row của case đó bị xoá theo. ⇒ tầng này KHÔNG sống sót qua
  xoá case.
- **`co_stock_events`** (mig `009`) — audit log **append-only** theo lot
  `(declaration_no, line_no, customs_code)`. Mỗi lock/release/adjustment ghi 1 dòng mang
  `case_id`, `sheet_product_code`, `qty_delta`, `actor`, `recorded_at`. Surface qua modal
  "Lịch sử" mỗi lot (`/co-stock/lot-history` → `events_for_lot`).

## Luồng xoá thực tế (`delete_case_record`, `co_case_store.py:210`)

1. Chặn nếu case completed (`co_case_delete_block_reason`; nhánh `origin_calculation_lock` đã bỏ
   ở Phase 1).
2. `claims_summary_for_case` → nếu còn claim `locked` mà caller **không** truyền
   `release_claims=True` → raise `CaseHasActiveClaimsError(count, lots)` (modal xác nhận).
3. Nếu confirm → `release_all_claims_for_case`: **UPDATE** claim `status='released',
   released_at=now()` + ghi event `claim_release` `actor='ledger:case_delete'` cho từng lot.
   Round-trip 1 lần cho mọi sheet. **Mục đích thật của bước này là ghi EVENT** — vì claim row sẽ
   bị cascade xoá ở bước 4 đằng nào cũng mất.
4. Sau đó xoá case row: app chỉ phát `delete from co_cases` + `co_supporting_files`
   (`workflow_state_store.delete_case:536`), nhưng **DELETE `co_cases` kích hoạt FK CASCADE → xoá
   luôn `co_stock_claims` của case** (mig 016). rmtree upload dir.

→ Thứ tự đúng: nhả claim + ghi audit (event) TRƯỚC khi xoá case, nên event không bao giờ trỏ vào
case_id "chết giữa chừng"; claim row bị prune nhưng event đã lưu xong.

## Kết luận theo từng câu hỏi

1. **Tồn có nhả không? CÓ — đúng.** Claim chuyển `locked→released`; vì remaining chỉ cộng
   `locked`, lot tự trả về pool. Guard bắt buộc confirm. Gap HIGH #2 ("silent Tồn CO leak")
   thực sự đã đóng — không còn orphan claim ghim lot vĩnh viễn.

2. **Lịch sử ghi nhận thế nào? CHỈ tầng event sống sót.**
   - `co_stock_claims`: **bị cascade xoá** khi xoá case (FK mig 016). Dòng `released` KHÔNG còn
     sau xoá — không thể dựa vào bảng này để truy vết hậu-xoá.
   - `co_stock_events`: **append-only, KHÔNG có FK** → miễn nhiễm cascade, sống sót. Giữ
     `claim_lock` + `claim_release(actor='ledger:case_delete')` với `case_id + lot + qty_delta +
     recorded_at`. Đây là dấu vết DUY NHẤT còn lại. (Mig 016 cố ý chọn CASCADE đúng vì events đã
     giữ lịch sử — prune claim là "clean prune".)

3. **Còn truy được hồ sơ nào từng giữ lot? CÓ case_id, KHÔNG có danh tính người-đọc-được.**
   Mở modal "Lịch sử" của lot → vẫn thấy dòng release mang `case ${case_id}`. Nhưng chỉ là id
   máy `co-case-<hex>`; sau khi `co_cases` bị xoá cứng, không còn gì map
   `case_id → case_code / invoice_no / title / co_form_type`. Truy ngược dừng ở một id treo.

## Đánh giá — hợp lý tới đâu

**Tầng đúng-tồn: vững.** Không leak, có guard, thứ tự thao tác chuẩn. Audit-trail dạng **event**
(`co_stock_events`) miễn nhiễm cascade và sống sót; ledger claim thì bị prune theo case (đúng
thiết kế mig 016 vì event đã giữ lịch sử). Đây là điểm rủi ro nhất và nó ổn.

**Tầng truy-vết: một phần.** Dữ liệu sống sót nhưng **không đọc được bằng người** và **không
liệt kê được** sau xoá cứng:

- **GAP A (MEDIUM, traceability).** `co_stock_events` không có `case_code/invoice/title`; modal
  render `case ${case_id}` thô. Với case sống đã khó đọc; với case đã xoá là **bất khả hồi** —
  auditor thấy id treo, không biết bộ CO nào đã tiêu thụ lot đó. (`source_co_no` có cột nhưng
  để rỗng trên claim event.)
- **GAP B (MEDIUM, discoverability).** `events_for_case(case_id)` đòi **biết trước** case_id.
  Sau xoá cứng không có bảng/view "các hồ sơ đã xoá", không `deleted_at/deleted_by`. Không thể
  bắt đầu từ "cho xem hồ sơ đã xoá" — chỉ từ một lot đã nghi sẵn.
- **GAP C (LOW).** Bản thân hành vi **xoá case** không sinh event riêng; chỉ có các release theo
  lot. Case giữ **0 claim** mà bị xoá → **không để lại dấu vết nào** ở bất kỳ đâu. `actor=
  'ledger:case_delete'` có phân biệt nguyên nhân (tốt) nhưng delete-release không set `notes`
  (relock-release thì có).
- Minor (plus): dòng `released` tích luỹ mãi (không archival) — volume không đáng kể, lại lợi
  cho audit.

## Hướng khắc phục (chưa làm — chờ quyết)

- **R1 (rẻ, lợi cao) — snapshot danh tính case lên release event.** Lúc nhả khi xoá, ghi
  `case_code/invoice/title` vào `notes` (hoặc tận dụng `source_co_no`) để modal lịch sử vẫn
  đọc được sau khi case mất. Không đổi schema.
- **R2 (trung) — soft-delete/tombstone case.** Giữ `deleted_at/deleted_by` (hoặc bảng
  `co_case_deletions`) để `case_id` luôn resolve được + có view "hồ sơ đã xoá" liệt kê được.
  List page đã có `archived` (khác delete) — có thể route "xoá" của case gần-hoàn-tất sang
  archive, để hard-delete cho nháp.
- **R3 (rẻ) — emit 1 event `case_delete`** (kể cả không gắn lot) gồm case_id+code+actor+
  số claim đã nhả, để delete 0-claim vẫn có footprint. (Cần thêm `case_delete` vào `EVENT_TYPES`
  + nới CHECK constraint mig `009` — lưu ý event không gắn lot sẽ bị `record_event` bỏ vì thiếu
  khoá lot; cần đường ghi riêng hoặc bảng audit case-level.)

## Tham chiếu
- `app/co_case_store.py:210` `delete_case_record`; `:254` block-reason.
- `app/co_stock_ledger.py:414` `release_all_claims_for_case`; `:391` `claims_summary_for_case`;
  `:464` `used_qty_by_lot` (remaining chỉ cộng `locked`).
- `app/co_stock_events_store.py` (`record_events`, `events_for_lot`, `events_for_case`); mig
  `db/migrations/009_*.sql`.
- `app/workflow_state_store.py:536` `delete_case` (phát DELETE `co_cases`+`co_supporting_files`;
  CASCADE `co_stock_claims` qua FK).
- `db/migrations/016_co_stock_claims_case_fk.sql` — FK `co_stock_claims_case_fk` `ON DELETE CASCADE`.
- UI: `app/templates/co_stock.html:266-287` (render `case ${ev.case_id}` thô);
  `app/routers/co_stock.py:331` `/co-stock/lot-history`.
- Liên quan: `.ai/audits/2026-05-28-case-sheet-stock-state-machine.md` (Gap 4 lock),
  feedback #1 "xoá hồ sơ".
