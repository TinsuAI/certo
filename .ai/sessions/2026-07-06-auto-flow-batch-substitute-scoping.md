# Session 2026-07-06 — Scoping: flow CO tự động hoá (batch tính + thay NVL thiếu ở sheet tổng hợp)

> Đây là **handoff/scoping artifact**, chưa code gì. Mục đích: chốt hướng redesign
> để session sau chạy `/discover` (hoặc skill `research`/`codebase-design`) rồi mới làm.

## Bối cảnh (khách phản hồi)
Flow CO hiện tại **quá nhiều thao tác**: 1 lô 30 SP phải làm 30 sheet → mất rất nhiều
thời gian. Cuộc họp trước đã thống nhất làm thêm **1 flow tự động hoá hơn**, nhưng
**phải review kỹ logic** để đảm bảo tính chính xác của hồ sơ + cách tính + trừ lùi.

## Flow lý tưởng (đã bàn với khách)
- **Nhập TKX** → tự động load các SP + BOM tương ứng từng SP → **tự tính tất cả sheet**.
- Nếu **thiếu tồn**: đưa các NVL bị thiếu vào một **sheet tổng hợp**. Ở đó user thay
  **tất cả** hoặc chỉ **phần NVL còn thiếu** sang NVL khác; thay đổi **sync xuống từng
  sheet SP** riêng lẻ.
  - VD: 10 mặt hàng XK đều dùng NVL A, CO Stock chỉ đáp ứng 8 SP đầu, 2 SP cuối phải
    thay → user chọn **thay phần thiếu** (2 SP) hay **thay hết** (10 SP). Thay xong
    update vào các sheet sản phẩm.
- Vẫn **sửa được từng sheet riêng** để tối ưu giá trị **LVC**.
- Sau khi thay có **nút check / tính lại** để đảm bảo logic — không tranh nhau CO Stock,
  không lỗi logic khác.
- Câu hỏi của khách: *"Logic tranh tồn có thể review lại — thay vì bảo vệ cả sheet, chỉ
  những NVL chung mới có thể tranh tồn của nhau, đúng không?"*

## Research findings (đã đọc code — VERIFY lại trước khi làm, đừng tin sẵn)

### 1. Tranh tồn HÔM NAY đã là per-material, không phải per-sheet → khách nói đúng
- `case_allocation_pool()` — **`app/web/co_case_context.py:1746`** — gom lô tồn thành
  dict keyed theo **mã NVL** (`co_stock_allocation_pool`).
- Khi tính cả case (`prepare_case_origin_products`), mọi SP rút từ **cùng 1 pool object**
  và trừ dần `_allocation_remaining_qty` tại chỗ. → Hai SP **không chung mã NVL** thì
  **không hề đụng** lô của nhau. Tranh tồn về thuật toán vốn đã giới hạn đúng ở NVL chung.

### 2. Cái ép tuần tự KHÔNG phải do logic trừ tồn — là rule workflow riêng
- `origin_sheet_action_error()` — **`app/web/co_case_context.py:1396`** — chặn
  `calculate`/`lock` SP N nếu **bất kỳ SP trước** (theo index dòng) chưa locked
  (`previous_unlocked`), và chặn tính lại N nếu **SP sau** đã locked (`later_locked`).
  Thuần **index-order**, **không** biết 2 sheet có chung NVL hay không.
- Lý do tồn tại: lock ghi claim ledger per-sheet (`record_sheet_lock_claims`); tính lại
  SP sau cần thấy claim đã chốt của SP trước → gate tuần tự là để **audit/consistency**,
  KHÔNG phải yêu cầu bắt buộc của thuật toán phân bổ.

### 3. Redesign khả thi (vừa, không nhỏ)
Thay index-gate bằng **graph material-overlap**: chỉ sheet **chung ≥1 mã NVL** với sheet
đang sửa/chưa chốt mới cần khoá chờ nhau; sheet disjoint tính/chốt độc lập (kể cả song song).
- Sửa `origin_sheet_action_error`: so **tập mã NVL giao nhau** thay vì so index.
- Đảm bảo thứ tự ghi claim ledger cho NVL chung vẫn **deterministic** dù claim đến từ
  sheet nào trước (`record_sheet_lock_claims`).

## Backend batch đã BUILD sẵn (Mục 6) — gần đúng ý khách, UI đang gate tắt
Session `2026-06-19-muc6-bom-batch-flow.md`, shipped `1313ba0`. Routes ở
**`app/routers/co_case.py`**:
- `preview_stock_all_route` (**:1686**) — chạy tồn cả case **không commit**, trả summary
  thiếu tồn.
- `bulk_substitute_route` (**:1697**) — thay 1 NVL trên nhiều SP trong 1 call, **sync từng
  sheet** qua `material_overrides`, skip sheet đã locked + báo lý do.
- `bulk_lock_route` (**:1783**) — chốt tất cả, tôn trọng cùng gate tuần tự.

**Còn thiếu so với flow lý tưởng:**
- (a) UI đang gate tắt ("đang xây dựng", `834e1da` — routes nguyên vẹn).
- (b) Chưa có chế độ **"thay phần thiếu vs thay hết"** tự động. Hiện caller phải tự liệt
  kê từng cặp `{product_code, material_code, substitute_code}`; chưa có summary kiểu
  *"NVL A thiếu ở 2/10 SP → thay 2 hay thay cả 10?"*.
- (c) Gate tuần tự (#2) vẫn over-block bulk-lock giữa các sheet không liên quan.

## Rủi ro chính xác — phải chặn TRƯỚC khi mở batch
- **DC3a** (BACKLOG): update-BOM qua Data Hub propose-bom **lọt rác** (`build_bom_proposal_rows`
  ~`co_case.py:2647`). **DC3c**: `declarable_unmatched=0` **thổi phồng LVC** khi NVL chưa
  match. Batch-recalc chạy nhiều sheet cùng lúc → **nhân lỗi ra cả lô** thay vì 1 sheet.
- **Rule cứng 2026-06-25** ([[bangke-export-equals-web-invariant]]): export = **render
  thuần** bước Tính, KHÔNG logic riêng → **"sheet tổng hợp" phải là VIEW** trên state đã
  tính của từng sheet, KHÔNG phải đường tính song song riêng.

## Next step
Vùng rủi ro cao (**CO calculation parity** — CLAUDE.md). Chạy `/discover` /
skill `research`/`codebase-design` để scope redesign #3 + wiring batch UI (a/b/c) +
guard DC3a/DC3c trước, **chưa code vội**.

## Ghi chú vận hành
- Skills Matt Pocock (21 cái) đã update trên đĩa `~/.claude/skills/` (2026-07-06 12:34)
  nhưng **không** load được vào session cũ — session mới sẽ có (`research`, `implement`,
  `tdd`, `domain-modeling`, `codebase-design`, `handoff`, `triage`…).
