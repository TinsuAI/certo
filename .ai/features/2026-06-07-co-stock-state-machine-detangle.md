# Feature: Gỡ rối state machine giữ-tồn / chốt-sheet / đóng-hồ-sơ (CO)

Discovery brief. Chưa code. Nối tiếp audit `.ai/audits/2026-06-07-delete-case-stock-history-audit.md`
và state-machine audit `.ai/audits/2026-05-28-case-sheet-stock-state-machine.md` (Gap 4 = bug khoá A).

## Bối cảnh — 5 chiều trạng thái đang đan nhau

| Chiều | Phạm vi | Trạng thái | Vai trò |
|---|---|---|---|
| **A** `origin_calculation_lock` | mỗi **khách** | active/released/hết-hạn (TTL 60′) | mutex bước *tính*; hard-block 409 hồ sơ anh em; **không tự nhả** (bug) |
| **B** `origin_sheet_status` | mỗi sheet | draft→calculating→calculated→locked (+stale) | trạng thái làm việc của bảng kê |
| **C** `co_stock_claims` | mỗi sheet×lot | locked/released | **lớp DUY NHẤT thực thi bất biến tồn** |
| **D** case `status` | mỗi hồ sơ | open/completed | đóng băng để nộp |
| **E** thứ tự chốt sheet | trong 1 hồ sơ | suy ra, không lưu | chốt tuần tự; mở chốt từ sheet cuối |

**Bất biến duy nhất cần bảo vệ:** Σ claim `locked` mỗi lot ≤ `remaining_qty` (tồn đã fold trừ-lùi).

**Phát hiện then chốt (đã xác minh trong code):**
- Hành động đụng tồn thật = chốt sheet → `record_sheet_lock_claims` (`co_case.py:1637`) →
  `co_stock_ledger.record_sheet_lock` (`co_stock_ledger.py:150`). Endpoint chốt
  (`lock_co_case_origin_sheet:1609`) **KHÔNG** gọi `acquire_origin_calculation_lock`.
- ⇒ Mutex **A trực giao với an toàn tồn**. A chỉ chặn evaluate/calculate/export
  (`pages.py:199`, `co_case.py:1063/1513`). Bỏ A không đụng lớp an toàn C.
- **Khe đua over-claim CÓ THẬT:** check availability (`co_stock_ledger.py:205-218`) là
  `SELECT … remaining_qty … sum(other locked claims)` **không có `FOR UPDATE`**, isolation mặc
  định READ COMMITTED, rồi DELETE+INSERT. Hai case cùng chốt một lot trong cùng cửa sổ ms có thể
  cùng qua check rồi cùng insert → vượt tồn. A không đóng khe này (không giữ khoá lúc commit).
- **E là LOAD-BEARING cho kết quả (đã sửa nhận định cũ):** lúc *tính*, pool bị trừ live bởi mọi
  claim locked toàn khách (`co_case_context.py:364` `apply_used_qty`; `used_qty_by_lot` không lọc
  case). Phân bổ = greedy tuần tự trên pool chung ⇒ **phụ thuộc thứ tự**: A chốt trước thì B thiếu
  phải đổi NVL; B chốt trước thì A phải đổi. E ép thứ tự đó thành xác định (theo thứ tự tài liệu).
  Bỏ E = kết quả không xác định / chốt xong hỏng phải tính lại. ⇒ **Giữ E, KHÔNG nới.** (Đây là
  *xác định kết quả nghiệp vụ*, không phải chỉ UX.)

## Quyết định (user-confirmed 2026-06-07)

- **Bỏ A:** đã chốt. Bỏ hẳn per-client mutex.
- **Giữ E:** đã chốt. E quyết định kết quả nghiệp vụ (xem trên), không nới.
- **Tách Load BOM / Tính bảng kê:** đã chốt — làm **Phase 2** (xem dưới).

## Scope — Phase 1: bỏ A + đóng khe đua (backend, rủi ro đúng-đắn/tồn)

**Trong phạm vi:**
1. **Bỏ mutex A** (`origin_calculation_lock`) — xoá chiều A khỏi acquire/release/context/UI; gỡ
   luôn bug Gap 4 (kẹt khoá 60′). Lớp an toàn tồn không suy giảm.
   - Đánh đổi user đã chấp nhận: hai nhân viên tính song song được; hiếm khi người chốt sau phải
     tính lại 1 sheet (tự lành qua overlay live + over-claim check). Đổi lấy bỏ block + bỏ bug 60′.
2. **Đóng khe over-claim bằng `SELECT … FOR UPDATE` trên `co_stock_rows`** (KHÔNG advisory lock —
   xem Review finding #2). Chỉ cần ở `record_sheet_lock` (đường INSERT duy nhất; `record_sheet_release`
   + `release_all_claims_for_case` chỉ nhả, không over-claim). `record_sheet_replace` **không tồn tại**.
3. Giữ nguyên C, D, E, và B-như-mặt-của-C.

**Ngoài phạm vi Phase 1:**
- Tách Load BOM / Tính → Phase 2.
- Nới/bỏ E — KHÔNG làm (E load-bearing, giữ).
- Dọn trạng thái transient của B (`calculating`/`stale`) — cruft, ưu tiên thấp.

## Scope — Phase 2: tách "Load BOM" khỏi "Tính bảng kê" (frontend+context, rủi ro UX)

**Vấn đề hiện tại:** nút nhãn "Load BOM" (`co_case.html:1178`) bắn vào `/calculate`, mà
`/calculate` (`co_case.py:1569-1607`) làm 4 việc một lúc: (a) nạp BOM artifact → khai triển NVL
(`prepare_case_origin_sheet`), (b) phân bổ tồn + tính xuất xứ, (c) `mark_origin_sheets_stale` các
sheet sau, (d) [hôm nay] chiếm A. Không thể nạp BOM để xem/sửa NVL mà không chạy cả phân bổ tồn.

**Mục tiêu:**
1. **Load BOM** (mới, nhẹ): chỉ chạy (a) — nạp công thức NVL vào sheet, status → `bom_loaded`.
   Không đụng tồn, không cascade.
2. **Tính bảng kê** (`/calculate` thu hẹp): chạy (b)+(c) — phân bổ tồn + xuất xứ + stale-cascade,
   status `bom_loaded → calculated`.
3. Thêm 1 trạng thái B = `bom_loaded`; cập nhật gating (`origin_can_calculate`/`can_lock`), nhãn,
   nút.

**Rủi ro Phase 2:**
- `prepare_case_origin_sheet` phải tách được (a) khai triển BOM khỏi (b) phân bổ tồn — **rủi ro
  chính, đọc kỹ trước.** Nếu fused chặt thì refactor lớn hơn.
- substitute/edit-row/add-row/save/propose-bom hiện giả định sheet đã `calculated` — ở `bom_loaded`
  phải cho sửa NVL nhưng chưa có kết quả xuất xứ.
- Lợi ích phụ: nền cho #14 (auto-load BOM mặc định không tính nặng) + #13 (load loạt → tính loạt).
- Freshness của `remaining_qty` snapshot (memory `origin-costock-freshness-deferred`) — vấn đề khác.
- Truy-vết xoá hồ sơ (R1/R2/R3 trong audit delete-case) — backlog riêng.

## Scope — Phase 3 (sau): dọn nhiễu lịch sử tồn CO (display-only)

Vấn đề: chốt→mở chốt→chốt ghi cả `claim_lock` (−qty) lẫn `claim_release` (+qty) vào
`co_stock_events` → modal "Lịch sử" mỗi lot nhiễu (chỉ dedup re-lock y hệt khi sheet **còn** chốt,
`co_stock_ledger.py:296-323`; sau mở-chốt thì không). KHÔNG sai tồn (remaining chỉ cộng `locked`).
Hướng: **giữ ghi đủ ở tầng dữ liệu** (audit trail thật), chỉ đổi **hiển thị** `events_for_lot` —
mặc định gộp net theo (hồ sơ, lot) / phân biệt nháp vs đã-cam-kết (lúc đóng hồ sơ), nút "Chi tiết"
bung event thô. Rủi ro thấp (không đụng ledger sống). Gộp chung discovery với truy-vết xoá hồ sơ
(R1/R2/R3 audit delete-case). Tách hẳn khỏi Phase 1.

## Review findings (3 agent độc lập, 2026-06-07) — đã sửa kế hoạch

1. **Khe over-claim CÓ trong code nhưng KHÔNG kích hoạt được trên prod hiện tại.** Prod `--workers 1`
   (`Dockerfile:30`) + đoạn check→INSERT trong `record_sheet_lock` **không có `await` ở giữa** →
   event loop chạy trọn vẹn → serialize tình cờ. Đua chỉ thật khi >1 worker / nhiều instance. ⇒
   tiềm ẩn, không phải bug sống. (vẫn vá vì là bảo hiểm đúng-đắn + user chọn làm.)
2. **Advisory-lock-trên-claims KHÔNG đủ.** Check đọc `remaining_qty` từ snapshot `co_stock_rows`,
   mà snapshot bị **materializer ghi đè ở transaction khác** (`co_stock_materializer.py:188-190`
   `update … where client_id=? and source_row=?`) không giữ advisory lock của claims. Advisory chỉ
   serialize claim-vs-claim, bỏ sót claim-vs-refresh. ⇒ Dùng `FOR UPDATE` trên `co_stock_rows`
   (cùng PK `(client_id, source_row)` mà materializer khoá) để serialize CẢ HAI.
3. **Bỏ A an toàn trên prod (verify).** Store prod = PG per-case (`update_case_record` per-case key
   → hai hồ sơ khác = hai row khác, không lost-update); ledger tồn có transaction +
   `StockOverclaimError` riêng ở `/lock` (vốn không giữ A); snapshot refresh có lock riêng
   `_co_stock_refresh_inflight_lock`; `_CO_CASE_SOURCE_CACHE` per-case. A thuần khoá serialize mức
   UX. *Caveat:* chỉ đa-HOST file-mode mới mất serialization khi bỏ A — không áp dụng prod PG 1-container.
4. **Lỗi factual trong brief cũ (đã sửa):** `record_sheet_replace` không tồn tại; hàm mutating đúng
   là `record_sheet_lock`/`record_sheet_release`/`release_all_claims_for_case`; `mark_origin_sheets_stale`
   còn được `/calculate:1597` gọi → KHÔNG xoá kèm A.

## Decisions

- **D1. Đóng over-claim = `SELECT … FOR UPDATE` trên `co_stock_rows`** (thay advisory lock). Vì câu
  check hiện có GROUP BY/aggregate (`co_stock_ledger.py:205-218`) — Postgres CẤM `FOR UPDATE` với
  GROUP BY — pattern là **2 statement cùng transaction**: (1) `select 1 from co_stock_rows where
  client_id=%s and source_row = any(%s) order by source_row for update` (khoá đúng lot, sort để
  deadlock-ổn định), rồi (2) chạy câu aggregate check cũ nguyên trạng, rồi (3) DELETE+INSERT. PK
  `(client_id, source_row)` (mig `001:102`) đảm bảo đúng 1 row/lot và serialize luôn với materializer
  UPDATE cùng row. Không schema change.
  - Giới hạn đã biết (giữ ngoài phạm vi): nếu client chưa có snapshot row nào, check bị **skip**
    (`co_stock_ledger.py:197-203`) → FOR UPDATE không khoá gì (không có row). Lỗ C3 này có sẵn,
    không tệ thêm; out of scope Phase 1.
- **D2. A bị xoá hẳn, không chỉ disable.** Xoá: `acquire/release/active_origin_calculation_lock`,
  `origin_calculation_lock_is_active`, TTL const, 3 context flag (`co_case_context.py:2697-2699`),
  banner UI, endpoint `/origin-lock/release`, nhánh release trong close (`co_case.py:1408-1414`),
  `co_case_delete_block_reason` nhánh lock, 409-paths trong `/evaluate` (`pages.py:199-213`),
  `/calculate` (`co_case.py:1513-…`), `/export` (`co_case.py:1063-…`). **GIỮ** `mark_origin_sheets_stale`
  (dùng bởi `/calculate:1597`); nếu xoá endpoint `/origin-lock/release` thì rút phần gọi
  `mark_origin_sheets_stale(case, 0)` trong đó, không xoá hàm.
- **D3. Không đổi hành vi người dùng nhìn thấy** ngoài việc *hết* thông báo "hồ sơ X đang giữ
  phiên tính tồn" và *hết* nút "nhả phiên". Chốt/mở-chốt/đóng/mở-lại giữ nguyên.

## Risks

- **R-test. Test phụ thuộc A:** chỉ `tests/test_co_demo.py` (1 file) chạm `origin_calculation_lock`.
  Blast radius nhỏ — cập nhật/loại assertion mutex khi bỏ A.
- **R-race-test. Test khe đua phải đúng.** (a) BẮT BUỘC `BARRY_DATABASE_URL` thật — file-mode
  `_ledger_available()=False` → `record_sheet_lock` no-op → test xanh giả (memory
  `test-env-filemode-vs-datahub`). (b) Phải seed `co_stock_rows` snapshot, nếu không nhánh skip
  (`co_stock_ledger.py:197-203`) bỏ qua check → test xanh giả. (c) Vì 1-worker + không-`await`
  serialize tình cờ, test threading Python KHÔNG repro; phải dùng **2 psycopg connection thật** xen
  kẽ thủ công: conn1 SELECT-check (chưa commit) → conn2 SELECT-check → cả hai INSERT → assert vượt
  tồn (chứng minh khe), rồi thêm FOR UPDATE → conn2 block tới khi conn1 commit → assert không vượt.
- **R-deadlock. Thứ tự khoá thống nhất.** `record_sheet_lock` sort source_row trước khi FOR UPDATE.
  Materializer UPDATE đi từng lot — Postgres tự xử thứ tự ở mức row; rủi ro deadlock thấp nhưng giữ
  sort cho ổn định.
- **R-rollback. Field A mồ côi sau deploy.** Bỏ A để lại `origin_calculation_lock` trong payload
  `co_cases`/`cases.json` cũ — code mới chỉ cần NGỪNG đọc (không crash nếu field còn). Không cần
  migration xoá; forward-compat: bỏ qua field lạ.

## Open Questions

1. ~~Prod mấy worker?~~ ✅ **1 worker** (`Dockerfile:30 --workers 1`, compose không override). ⇒ khe
   đua latent, không sống; FOR UPDATE là bảo hiểm cho tương lai đa-worker (user vẫn chọn làm).
2. ~~co_stock_rows 1 row/(client,lot)?~~ ✅ **Đúng 1** — PK `(client_id, source_row)` (mig `001:102`).
   ⇒ FOR UPDATE khoá đúng lot + serialize với materializer cùng PK.
3. ~~Code path khác ghi claims?~~ ✅ Mutation đúng = `record_sheet_lock` (INSERT/DELETE :261/267),
   `record_sheet_release` (UPDATE :362), `release_all_claims_for_case` (UPDATE :436). Chỉ
   `record_sheet_lock` cần FOR UPDATE (đường INSERT duy nhất).
4. ~~mark_origin_sheets_stale dùng đâu?~~ ✅ Cũng ở `/calculate:1597` → GIỮ hàm; chỉ rút lời gọi
   trong endpoint `/origin-lock/release` khi xoá endpoint đó.
5. ~~E cố ý hay tình cờ?~~ ✅ Cố ý — đúng nghiệp vụ; giữ E.
6. Phase 2: `prepare_case_origin_sheet` (`co_case_context.py:939-1004`) — ✅ TÁCH ĐƯỢC NHƯNG PHẢI
   REFACTOR: BOM-expansion + allocation fuse trong `origin_material_from_bom_row`/
   `origin_product_from_invoice_match`; override sửa NVL key theo *chỉ số dòng material* nên Load BOM
   vẫn phải khai triển ra `product.materials` (chỉ bỏ allocation) + thêm status `bom_loaded` (enum
   hiện `draft/calculating/calculated/locked/stale`, `co_case_context.py:33-38`).

## Next step

**Phase 1 — `/tdd`:** (a) test 2-connection DB thật (seed `co_stock_rows`) chứng minh khe over-claim
hiện có; (b) thêm `SELECT … FOR UPDATE` co_stock_rows vào `record_sheet_lock` → test xanh; (c) xoá
mutex A (D2) + cập nhật `tests/test_co_demo.py`. Rồi `/rev` → commit. **Phase 2** (tách Load BOM /
Tính) = discovery riêng sau.
