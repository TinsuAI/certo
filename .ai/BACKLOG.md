# Backlog

Durable backlog (survives handoffs — STATUS.md Next Steps is the prioritized slice). Items below
are captured, not yet scoped. Add `/discover` before non-trivial ones.

## UI / UX

### B1 — "Đổi công ty" / "Đổi hồ sơ" → modal, không redirect
**DONE 2026-06-08.** Cả hai giờ là modal picker lazy-fetch fragment (không redirect). Endpoint
`GET /clients/picker` (`pages.py`, đăng ký trước `/clients/{client_id}`) + `GET /clients/{id}/co-case-picker`
(`co_case.py`); template `_picker_clients.html` / `_picker_cases.html`; JS picker chung trong
`base.html` (`[data-picker-open]` → fetch → inject); CSS `.picker-*`. Highlight mục đang xem. Verified
local (johnson-vn) + screenshots `.ai/screenshots/2026-06-08-ui-backlog-b/`.

<details><summary>Ghi chú gốc</summary>

Hiện cả hai là link redirect sang trang khác:
- `Đổi công ty` — `app/templates/_client_nav.html:8` → `href="/clients"`.
- `Đổi hồ sơ` — `app/templates/co_case.html:583` → `href="/clients/{id}/co-case"`.
Đổi thành modal picker (chọn ngay trong context, không rời trang). Có thể tái dùng pattern modal
đã có (create-case modal trong case-list redesign `ee70a4b`).
Added: 2026-06-07.

</details>

### B2 — Review trạng thái các bước workflow của 1 hồ sơ (hiển thị chưa make sense)
**DONE 2026-06-08 (`0374edb`, `/tdd`).** Brief `.ai/features/2026-06-08-workflow-step-status-display.md`.
`co_case_step_status` giờ trả `{status, label}`; tập trạng thái mới **done/in_progress/attention/todo**
với nhãn theo ngữ cảnh từng bước. Bước 3 derive từ `products[].origin_sheet_status` (cùng nguồn
`co_case_status_view`) ⇒ chốt hết → `done` "Đã chốt N/N" (hết kẹt ở "Cần soát"). Bỏ "Preview" +
dead `wip` (class+badge+CSS); `todo` mute bằng color token (không opacity); thêm `in_progress` (xanh
dương) tách khỏi `attention` (vàng). Test `tests/test_co_case_step_status.py` (20 case). Verified:
544 passed + live render (done=green, attention=amber, todo=grey readable).

<details><summary>Ghi chú gốc</summary>

Per-step status hiện hiển thị không hợp lý. Liên quan trực tiếp tới state-machine detangle đang làm
(`.ai/features/2026-06-07-co-stock-state-machine-detangle.md`) — đặc biệt **Phase 2** (tách Load BOM
/ Tính bảng kê → thêm trạng thái `bom_loaded`) sẽ định nghĩa lại trạng thái sheet. Step keys:
`CO_CASE_WORKFLOW_STEP_KEYS` + sheet status enum (`co_case_context.py:33` draft/calculating/
calculated/locked/stale). Cần audit riêng: bước nào → trạng thái nào → nhãn nào, và sửa cái vô lý.
Nên gộp/đồng bộ với Phase 2. `/discover` trước.
Added: 2026-06-07.

</details>

### B3 — Bảng kê (origin-material-table): lỗi layout cột
**DONE 2026-06-08.** Nguyên nhân: cột `select` chèn thành cột 1 nhưng width vẫn dùng
`th:nth-child(N)` đánh số cho layout 11-cột cũ → lệch 1 cột (STT/Mã NVL phình, Tên NVL bị bóp).
Sửa: chuyển width sang selector `[data-origin-column]` (bền với chèn/đổi cột); cột select đổi
`width: 1%`→`2.6rem` (1% co lại dưới `table-layout: fixed` ⇒ clip checkbox = phần i). Verified:
johnson-vn 138 dòng — name 485px (rộng nhất), code 159, STT 68, select 57 + checkbox không clip.

<details><summary>Ghi chú gốc</summary>

Bảng `.origin-material-table` (`co_case.html:1388`; cột định danh qua `data-origin-column`).
- i) Cột chứa ô **select** bị che (clip). Nghi `overflow:hidden` ở container (giống bug
  `⋯`-dropdown bị clip đã sửa ở case-list — scope `overflow:visible`). Kiểm cột select + wrapper.
- ii) Cột **STT** (`data-origin-column="row"`, `:1392`) hơi to — thu hẹp.
- iii) Cột **Mã NVL** (`data-origin-column="code"`, `:1393`) quá to; **tên NVL**
  (`.origin-material-name`, `:1500`) cần nhiều diện tích nhưng quá bé — phân bổ lại width
  (Mã NVL nhỏ lại, tên NVL rộng ra). Widths ở `app/static/css/app.css` (tìm `origin-material-table`
  / `[data-origin-column]`). Lưu ý feedback #7 đã cho tên xuống 2 dòng + tooltip — kết hợp.
Added: 2026-06-07.

</details>

### B4 — UI trong từng hồ sơ: mở full-width thay vì 2 bên border
**DONE 2026-06-08.** Lề 2 bên = `.shell { width: min(1480px, …) }` (không phải `.app-frame` —
frame chỉ là overlay fixed). Sửa: thêm `{% block shell_modifier %}` vào `<main class="shell …">`
(base.html); co_case.html set `shell-wide` khi `co_case_active_step != "index"` (chỉ trang chi tiết
hồ sơ, không phải list/catalog/…); CSS `.shell-wide { width: calc(100vw - 32px); max-width: none }`.
Verified: detail = `shell shell-wide`, list + catalog = `shell` thường.

<details><summary>Ghi chú gốc</summary>

Trang chi tiết hồ sơ nên full-width. "2 bên border" hiện tại — cần xác định nguồn: hoặc
`.app-frame` (viền brand 3px full-viewport, `app.css:231`, từ app-identity `1f2b6dd`) hoặc
content container max-width (`.shell` `app.css:448` / các `max-width`). Xác minh cái nào tạo lề 2
bên trên trang hồ sơ rồi cho full-width **chỉ** ở context hồ sơ (đừng phá brand frame toàn cục nếu
đó là chủ đích identity). `/discover` nhẹ trước khi sửa.
Added: 2026-06-07.

</details>

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

## Performance

### P1 — "Tạo hồ sơ" → mở "Bảng kê C/O" lần đầu chậm
**DONE 2026-06-08 (origin cold-load) — merged + deployed `a1ac2ed`.** Brief
`.ai/features/2026-06-08-origin-cold-load-perf.md`. Chẩn đoán ban đầu ("full BCCT pull ~40s") SAI:
fetch DH đã hẹp (11ms). Thủ phạm thật = `origin_source_context` đọc TOÀN BỘ 60k-lô snapshot tồn
(`read_co_stock_rows_cached` 2.6s cold + copy/apply 540ms) ở tab-render, nhưng tồn đó KHÔNG dùng lúc
render (shells không nhận stock_rows; đường warm đã trả `stock_rows:[]`). Sửa phẫu thuật: cho cold
path trả `stock_rows:[]` như warm → **cold 3.5s→~0.1s**. Parity test `/calculate`+lock ra tồn y hệt.
Tách khỏi D1.

**Residual (vẫn open):**
- **Index (case list) 4.27s johnson-vn** — N+1 `co_stock_ledger.claims_summary_for_case`
  (`co_case_context.py:2760-2767`) per-case + `co_stock_summary` + source context. Batch/đổi 1 query.
- **(Optional) `/calculate` lot-scoping** — scope stock theo lô của sản phẩm (~540ms/calc).

<details><summary>Triệu chứng + đo gốc (giữ lại)</summary>

**Triệu chứng (user 2026-06-08):** tạo hồ sơ thấy "chạy lâu lắm".

**Đo thực tế (local, johnson-vn = 65846 dòng BCCT):**
- POST `/co-case/create` → **0.13s** (nhanh).
- Trang landing sau tạo (tab Vận đơn / shipment) → **~0.3s** (nhanh).
- **Mở "Bảng kê C/O" (origin) LẦN ĐẦU cho hồ sơ mới → 3.5s local; code tự ghi ~21–40s cho client lớn ở prod** (full BCCT + materials pagination từ Data Hub).
- Origin lần 2 (đã có snapshot) → ~0.3–1.1s.
- Phụ: trang DANH SÁCH hồ sơ (index) johnson-vn = **4.27s** (chỉ 3 hồ sơ); growatt 0.85s.

**Nguyên nhân:** bản thân hành động "tạo" nhanh. Độ trễ nằm ở **lần đầu build origin source-context** cho hồ sơ mới — đường `force_source_refresh=True` kéo TOÀN BỘ catalog BCCT + materials. Hồ sơ cũ nhanh vì dùng `origin_source_context` (snapshot CO-stock đã materialize + invoice_matches hẹp), không phải full pull.
- `app/routers/co_case.py:830` `create_co_case` (POST, nhanh) → 303 → `co_case_detail` (`:933`) bắn `preload_co_case_origin_context` (`:271`) trong executor (nền).
- `app/web/co_case_context.py:151` `co_case_light_context`: nhánh origin snapshot (`:162`, nhanh) vs non-origin skip-heavy (`:167`) vs `force_source_refresh` full pull (preload + lần đầu).
- Preload chỉ là best-effort: (a) bấm origin TRƯỚC khi preload xong → nuốt nguyên full pull đồng bộ; (b) preload không giảm khối lượng ~40s, chỉ dời khỏi response thread; (c) mỗi lần preload là một `force_source_refresh` full mới.
- Phụ — index 4.27s: vòng lặp per-case `co_stock_ledger.claims_summary_for_case` (`co_case_context.py:2760-2767`, N+1) + `co_stock_summary` + source context.

**Phương án (chưa chọn):**
1. **Lần đầu origin cũng dựa vào snapshot CO-stock + invoice_matches hẹp** thay vì full-catalog pagination (giống path hồ sơ cũ). Win lớn nhất nhưng đụng đúng máy refresh nguồn → **gắn chặt D1**.
2. **Thu hẹp pull theo declaration/invoice của hồ sơ** — hồ sơ mới chỉ cần materials cho invoice/TKX đã chọn, không cần cả catalog.
3. **Preload tin cậy + có tiến trình:** bắn preload ngay lúc POST tạo (không chỉ lúc GET shipment); tab origin hiển thị trạng thái "đang nạp dữ liệu nguồn…" + poll (pattern background dossier export) thay vì request treo ~40s.
4. **Warm cache theo client** (nightly / lần truy cập đầu) để origin đầu của mọi hồ sơ mới tái dùng.

Lưu ý: P/A 1+2 chồng lấn **D1** (cùng `co_case_source_context` / source refresh). Cân nhắc gộp discovery. `/discover` trước.

</details>

Added: 2026-06-08. Discovered: 2026-06-08.

## Testing / Infra

### T1 — Cô lập DB cho test (ngừng tích cruft vào DB dev)
**DISCOVERED 2026-06-08 → `.ai/features/2026-06-08-test-db-isolation.md`.** Test chạy có `.env`
(DB-backed) gọi endpoint thật vào Postgres dev dùng chung, luôn dùng seed client growatt/johnson,
**không dọn** → tích 845 case growatt (+ `bom_*`/`source_*` cruft) trong ~4 tuần; lòi ra ở picker
"Đổi hồ sơ". Đã purge growatt (backup `data/local/backups/growatt-cases-purge-2026-06-08.json`).
Đề xuất: conftest schema-isolation (`BARRY_DATABASE_SCHEMA=co_test_<worker>`, migrate + drop cascade
teardown) + guard chặn ghi vào schema `co`. Cần `/discover`: phân loại test tạo-vs-đọc-seed trước
khi sửa. Added: 2026-06-08.
