# Backlog

Durable backlog (survives handoffs — STATUS.md Next Steps is the prioritized slice). Items below
are captured, not yet scoped. Add `/discover` before non-trivial ones.

## UI / UX

### B1 — "Đổi công ty" / "Đổi hồ sơ" → modal, không redirect
Hiện cả hai là link redirect sang trang khác:
- `Đổi công ty` — `app/templates/_client_nav.html:8` → `href="/clients"`.
- `Đổi hồ sơ` — `app/templates/co_case.html:583` → `href="/clients/{id}/co-case"`.
Đổi thành modal picker (chọn ngay trong context, không rời trang). Có thể tái dùng pattern modal
đã có (create-case modal trong case-list redesign `ee70a4b`).
Added: 2026-06-07.

### B2 — Review trạng thái các bước workflow của 1 hồ sơ (hiển thị chưa make sense)
Per-step status hiện hiển thị không hợp lý. Liên quan trực tiếp tới state-machine detangle đang làm
(`.ai/features/2026-06-07-co-stock-state-machine-detangle.md`) — đặc biệt **Phase 2** (tách Load BOM
/ Tính bảng kê → thêm trạng thái `bom_loaded`) sẽ định nghĩa lại trạng thái sheet. Step keys:
`CO_CASE_WORKFLOW_STEP_KEYS` + sheet status enum (`co_case_context.py:33` draft/calculating/
calculated/locked/stale). Cần audit riêng: bước nào → trạng thái nào → nhãn nào, và sửa cái vô lý.
Nên gộp/đồng bộ với Phase 2. `/discover` trước.
Added: 2026-06-07.

### B3 — Bảng kê (origin-material-table): lỗi layout cột
Bảng `.origin-material-table` (`co_case.html:1388`; cột định danh qua `data-origin-column`).
- i) Cột chứa ô **select** bị che (clip). Nghi `overflow:hidden` ở container (giống bug
  `⋯`-dropdown bị clip đã sửa ở case-list — scope `overflow:visible`). Kiểm cột select + wrapper.
- ii) Cột **STT** (`data-origin-column="row"`, `:1392`) hơi to — thu hẹp.
- iii) Cột **Mã NVL** (`data-origin-column="code"`, `:1393`) quá to; **tên NVL**
  (`.origin-material-name`, `:1500`) cần nhiều diện tích nhưng quá bé — phân bổ lại width
  (Mã NVL nhỏ lại, tên NVL rộng ra). Widths ở `app/static/css/app.css` (tìm `origin-material-table`
  / `[data-origin-column]`). Lưu ý feedback #7 đã cho tên xuống 2 dòng + tooltip — kết hợp.
Added: 2026-06-07.

### B4 — UI trong từng hồ sơ: mở full-width thay vì 2 bên border
Trang chi tiết hồ sơ nên full-width. "2 bên border" hiện tại — cần xác định nguồn: hoặc
`.app-frame` (viền brand 3px full-viewport, `app.css:231`, từ app-identity `1f2b6dd`) hoặc
content container max-width (`.shell` `app.css:448` / các `max-width`). Xác minh cái nào tạo lề 2
bên trên trang hồ sơ rồi cho full-width **chỉ** ở context hồ sơ (đừng phá brand frame toàn cục nếu
đó là chủ đích identity). `/discover` nhẹ trước khi sửa.
Added: 2026-06-07.

## Tồn CO / Data Hub refresh

### D1 — Audit KỸ logic delta vs full + "refresh from Data Hub"
Đã vá 1 lỗ (`039baeb`): snapshot rỗng + `refresh_state.last_bcct_server_time` còn sót ⇒ delta no-op,
bảng tồn kẹt rỗng (repro johnson-vn: DH 65846 dòng BCCT / 60173 lô nhưng trang trống). Đó mới là 1
triệu chứng — cần audit **toàn bộ** `_refresh_co_stock_delta_or_full` / `_try_delta_refresh` /
`_full_refresh` / `record_refresh_state` (`co_case_context.py:2887+`) + `co_stock_materializer`
refresh_state. Góc cần soi:
- **Desync `refresh_state` ↔ `co_stock_rows`:** còn vector nào khác khiến delta âm thầm under/over-apply
  (qty đổi, dòng xoá không qua tombstone, lô bị block-by-claims rồi bỏ qua)? Snapshot-empty chỉ là 1.
- **Parity delta vs full:** chạy full rồi delta liên tiếp trên cùng dữ liệu phải ra cùng `co_stock_rows`.
  Cần test/parity-check định kỳ; nghi delta lệch khỏi full theo thời gian.
- **`bcct_row_count_at_refresh` ghi = tổng source count (65846) kể cả khi delta** → số liệu gây hiểu lầm,
  có thể che drift. Xem lại ý nghĩa field này.
- **Tombstone path:** `tombstone_source_rows` hash transaction_key → có khớp `source_row` materializer
  dùng để xoá không? Xoá hụt = tồn ảo.
- **UX tín hiệu:** refresh trả `ok:true, rows:0` không phân biệt "không có gì mới" vs "snapshot lỗi" —
  operator không biết. Cân nhắc surface mode/lý do (full vì rỗng, delta N thay đổi…).
- **`_probe_server_time` best-effort fail** → server_time trống → full mãi (chậm ~12s/lần Johnson).
Rủi ro: SAI TỒN (over/under-claim downstream). `/discover` + viết test parity trước khi sửa.
Added: 2026-06-07.
