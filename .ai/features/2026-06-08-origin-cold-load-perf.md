# Feature: P1 — "Tạo hồ sơ → mở Bảng kê C/O lần đầu" chậm

Discovery cho backlog **P1**. Sửa lại chẩn đoán ban đầu (KHÔNG phải "full BCCT pull ~40s").

## Bối cảnh đo được

Local, johnson-vn (60173 lô tồn, 65846 dòng BCCT):

| Bước | Thời gian | Ghi chú |
|---|---|---|
| POST `/co-case/create` | 0.13s | nhanh |
| Landing sau tạo (tab Vận đơn) | ~0.3s | nhanh |
| Mở **Bảng kê C/O lần đầu** (hồ sơ mới, cold) | **3.5s** | điểm chậm |
| Mở Bảng kê C/O (hồ sơ cũ, warm) | ~0.27s | nhanh |

Profile `origin_source_context` (cold, johnson-vn, 1 tờ khai):

| Thành phần | Thời gian | |
|---|---|---|
| `read_co_stock_rows_cached` (60173 lô) | **2595 ms** | đọc + JSONB-deserialize toàn bộ snapshot tồn của client |
| copy 60k dict + `apply_used_qty` | ~540 ms | CPU trên toàn bộ snapshot, MỖI lần load |
| `source_summary` | 58 ms | |
| `origin_invoice_matches` (1 tờ khai, narrow DH) | **11 ms** | KHÔNG phải thủ phạm |
| `declaration_file_counts` | 11 ms | |

## Nguyên nhân gốc

Độ trễ KHÔNG nằm ở Data Hub. Fetch BCCT đã hẹp (per-declaration, 11ms). "Full BCCT pull
~40s" chỉ là **fallback khi snapshot rỗng** (đúng địa hạt D1) — không phải đường thường.

Thủ phạm: `origin_source_context` (`co_case_context.py:356`, đường **cold** cho hồ sơ mới chưa có
`source_snapshot`) đọc **toàn bộ 60k-lô snapshot tồn của client** qua
`_calculate_stock_rows_from_snapshot` → `read_co_stock_rows_cached` (`co_stock_materializer.py:423`).

**Nhưng tồn đó không được dùng ở tab-render:**
- `prepare_case_origin_product_shells` (`co_case_context.py:853`) — đường render tab — **không nhận
  tham số `stock_rows`**. Phân bổ tồn chỉ xảy ra ở `prepare_case_origin_sheet` (lúc Load BOM/Tính).
- `stock_rows` từ source_context chỉ chảy vào `case_tkx_tkn_summary` (`:272`), mà hàm này **không hề
  đọc `stock_rows`** (chỉ lặp invoice_matches + products).
- Đường **warm** (`cached_origin_source_context`, `:497`) đã trả `"stock_rows": []` (`:514`) và render
  tốt trong 0.27s → bằng chứng tab-render không cần snapshot tồn.

Đây là tàn dư sau refactor Phase 2 (tách Load BOM): trước kia origin render cả sheet (cần tồn); sau
khi phân bổ dời sang `/calculate`, lần đọc snapshot ở tab-render thành vô dụng nhưng còn sót.

**Cache thrash (làm chậm lặp lại, không chỉ lần đầu):** `read_co_stock_rows_cached` invalidate theo
marker `(max(indexed_at), count)`. Mỗi lần materializer ghi (kể cả **background refresh** mà chính
`_calculate_stock_rows_from_snapshot` lên lịch khi snapshot stale) → advance `indexed_at` → cache vỡ
→ lần origin sau lại nuốt 2.6s. Trong phiên làm việc tích cực, 2.6s tái diễn liên tục.

## Scope

**Trong phạm vi:**
- Bỏ lần đọc 60k-lô snapshot tồn ở **tab-render** origin (đường cold `origin_source_context`).
  Trả `stock_rows: []` như đường warm. Kỳ vọng: cold origin 3.5s → ~0.1s.

**NGOÀI phạm vi (ghi nhận, chưa làm trong lần này):**
- Thu hẹp tồn ở `/calculate` theo lô của riêng NVL sản phẩm đó thay vì copy+apply toàn 60k lô
  (~540ms/lần). Đụng `case_allocation_pool` / logic phân bổ — rủi ro cao hơn, tách riêng.
- Index page (danh sách hồ sơ) 4.27s: N+1 `claims_summary_for_case` (`co_case_context.py:2760-2767`).
  Vấn đề riêng, không thuộc P1.
- Sửa fallback "snapshot rỗng → full pull" — thuộc **D1**.

## Decisions

- **Sửa phẫu thuật, không kiến trúc lại.** Chỉ ngừng đọc snapshot ở tab-render; `/calculate` giữ
  nguyên `_calculate_stock_rows_from_snapshot` + fallback của nó (vẫn cần tồn thật khi tính).
- **Tách khỏi D1.** Lần đọc thừa này độc lập với đúng/sai delta-vs-full. D1 vẫn cần làm riêng cho
  tính đúng tồn; P1 chỉ là không-đọc-khi-không-dùng.
- **Không hiển thị preview tồn ở tab-render trước Load BOM** — đã là hành vi hiện tại (mode_note:
  "bấm Load BOM trên từng sheet để tính NVL và tồn CO"); chỉ làm cho code khớp ý định đó.

## Risks

- **Mất tín hiệu "snapshot rỗng → full pull" ở tab-render.** Chấp nhận được: tab-render không tính
  toán; client mới chưa materialize chỉ thấy chưa-có-tồn cho tới khi Load BOM/Tính (vốn có fallback
  riêng). Cần xác nhận không có widget tồn nào trên tab origin đọc `source_context.stock_rows`.
- **Tồn là vùng nhạy cảm** (memory: nhiều bug SAI TỒN). Phải có test chứng minh `/calculate` và lock
  vẫn ra tồn y hệt trước/sau (parity), vì đó mới là nơi tồn thực sự được dùng.
- **Preload** (`preload_co_case_origin_context`) cũng đi qua `origin_source_context` → sẽ nhẹ theo;
  xác nhận `source_snapshot` vẫn được persist (nó dựng từ `source_summary`, không từ stock_rows → OK).

## Open Questions

- Có UI nào (origin tab/substitute modal) dựa vào `origin_source_context.stock_rows` ngay lúc render
  không? (Grep cho thấy chỉ `case_tkx_tkn_summary` nhận và bỏ qua — cần xác nhận lần cuối ở template.)
- Có muốn gộp luôn việc thu hẹp tồn ở `/calculate` (NGOÀI scope ở trên) không, hay để item riêng?

## Next step

`/tdd`: viết parity test trước —
1. `/calculate` + lock cho 1 sheet ra tồn/allocation y hệt trước và sau khi bỏ đọc snapshot ở render
   (đây là bằng chứng "không SAI TỒN").
2. Cold origin tab-render không gọi `read_co_stock_rows` (assert qua spy/mock hoặc đo).
Rồi sửa `origin_source_context` trả `stock_rows: []`. Đo lại cold origin johnson-vn.
