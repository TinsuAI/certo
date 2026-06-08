# Feature: Sửa hiển thị trạng thái các bước workflow (stepper hồ sơ C/O) — B2

Discovery brief. Chưa code. Backlog B2 (`.ai/BACKLOG.md`). Backlog gắn B2 với Phase 2 của
state-machine detangle — **nhưng Phase 2 đã ship rồi** (xem Decisions), nên B2 giờ là việc
hiển thị độc lập ở tầng case-level.

## Bối cảnh — HAI hệ "trạng thái" tách biệt, backlog gộp nhầm

| Hệ | Phạm vi | Trạng thái | Hàm/nguồn |
|---|---|---|---|
| **Stepper (case-level)** | thanh 5 bước của hồ sơ | ready / todo / review / preview | `co_case_step_status()` (`co_case_context.py:2832`), nhãn `CO_CASE_STEP_STATUS_LABELS` (`:145`) |
| **Sheet (per-product)** | mỗi bảng kê trong bước 3 | draft / bom_loaded / calculating / calculated / locked / stale | `origin_sheet_status`, `ORIGIN_SHEET_STATUS_LABELS` (`:32`) |

B2 nói về **stepper** (5 bước: Lô hàng / Chứng từ / Bảng kê C/O / TKX-TKN / Review). Hệ sheet
đã ổn (pill per-product hoạt động đúng). Render stepper: `co_case.html:585-594`.

Có **nguồn sự thật thứ ba** đã tồn tại: `co_case_status_view()` (`co_case_store.py:267`) tính
`sheets_total` / `sheets_locked` + status case-level (done/attention/progress) cho trang DANH SÁCH
hồ sơ + dashboard. Stepper hiện **KHÔNG** dùng nó ⇒ trang list nói "Đang xử lý / 2 bảng kê chưa
chốt" còn stepper bước 3 lại nói "Cần soát" — hai chỗ bất đồng.

## Triệu chứng "chưa make sense" (đã xác minh trong code)

1. **Nhãn "Preview" tiếng Anh** giữa rừng tiếng Việt (`CO_CASE_STEP_STATUS_LABELS:149`). Dùng cho
   bước 3 (origin) và bước 5 (review) lúc nạp dở.
2. **Bước 3 "Bảng kê C/O" không bao giờ phản ánh tiến độ thật.** Trạng thái "tốt nhất" của nó là
   `review`→"Cần soát" khi có invoice+products+bom_snapshot (`co_case_step_status:2872-2879`) — **kể
   cả khi đã chốt HẾT các sheet.** Không có trạng thái `calculated`/`locked`/`done`. Nhân viên chốt
   xong toàn bộ vẫn thấy "Cần soát" (vàng). Đây là lỗi lõi. Giờ derive được từ `origin_sheet_states`.
3. **`review` và `preview` render Y HỆT nhau** — cùng màu `--warning` (`app.css:2485-2493`). Hai key
   khác nhau nhưng nhìn không phân biệt được.
4. **Dead code `step.wip`:** template render class `workflow-step-wip` + badge "W.I.P"
   (`co_case.html:590-592`) nhưng **không chỗ nào set `wip`** (grep toàn app = 0 producer). CSS cho
   nó cũng có (`app.css:4312,4451`). Rác — xoá hoặc wire.
5. **`workflow-step-todo` mờ bằng `opacity: 0.78`** (`app.css:2495-2497`) — vi phạm rule dự án
   "không dùng opacity làm mờ chữ" (memory [[css-no-opacity-muted-text]], bug tái diễn). Dùng color
   token thay vì opacity.
6. **Nhãn generic, không theo ngữ cảnh bước.** "Đủ/Thiếu/Cần soát" như nhau mọi bước; mỗi bước
   nghĩa khác nhau. Ví dụ bước "Chứng từ" `ready` chỉ cần `supporting_files` truthy → "Đủ" dù mới
   tải 1 file vô nghĩa. `todo`="Thiếu" gộp lẫn "chưa bắt đầu" và "đang thiếu input".

## Decisions

- **Phase 2 ĐÃ XONG (correction backlog).** `bom_loaded` đã có trong enum (`:34`), endpoint riêng
  `/load-bom` (`co_case.py:1465`) set `bom_loaded` không đụng tồn, tách khỏi `/calculate`
  (`:1545`), có CSS pill `origin-sheet-state-bom_loaded`. ⇒ B2 **không phải chờ Phase 2 nữa**; điều
  kiện backlog "gộp/đồng bộ với Phase 2" đã thoả. Bước 3 giờ derive trực tiếp từ `origin_sheet_states`.
- **Hợp nhất bước 3 với `co_case_status_view`.** Bước 3 (và toàn stepper) nên derive tiến độ bảng kê
  từ cùng `sheets_locked`/`sheets_total` mà trang list dùng — một nguồn sự thật, hết bất đồng.
- **Bỏ "Preview"; định nghĩa lại tập trạng thái stepper** theo ngữ nghĩa rõ + map nhãn theo từng bước
  (không generic). Đề xuất 4 nhóm trạng thái + màu:
  - `done` — xanh `--success` — bước hoàn tất.
  - `in_progress` — xanh dương/neutral `--primary` — đang làm (màu MỚI, tách khỏi vàng).
  - `attention` — vàng `--warning` — cần bổ sung/soát.
  - `todo` — muted bằng **color token** (không opacity) — chưa bắt đầu.
- **Nhãn theo bước (đề xuất, chốt khi implement):**
  1. **Lô hàng:** ref+market → `done` "Đủ"; chỉ 1 → `attention` "Thiếu thị trường"/"Thiếu invoice";
     không → `todo` "Chưa nhập".
  2. **Chứng từ:** có file → `done` "Đã tải"; không → `todo` "Chưa tải". (tín hiệu yếu — xem OQ2)
  3. **Bảng kê C/O:** không products → `todo` "Chưa có NVL"; có products chưa tính → `todo`/`attention`
     "Chưa tính"; đang làm (có sheet `bom_loaded`/`calculated`, chưa chốt hết) → `in_progress`
     "Đang làm · M/N chốt"; chốt hết → `done` "Đã chốt N/N".
  4. **TKX/TKN:** giữ logic `tkx_tkn_summary` (`:2857-2871`), đổi nhãn: ready→`done` "Đủ",
     review→`attention` "Thiếu tờ khai", todo→`todo` "Chưa có".
  5. **Review & Xuất:** đã xuất → `done` "Đã xuất"; ready → `done`/`in_progress` "Sẵn sàng"; else `todo`.
- **Xoá dead `wip`** (class + badge + CSS) trừ khi quyết wire lại (không có use case hiện tại → xoá).

## Risks

- `co_case_step_status` là hàm thuần được gọi mọi trang case (`co_case_workflow_steps:2802` từ
  `co_case_light_context:292`) + truyền `tkx_tkn_summary`, `invoice_matches`, `criteria_rows`. Đổi
  trả về phải giữ chữ ký + 4 key trạng thái template/CSS biết. **Thêm** key mới (`in_progress`,
  `done`) cần CSS class tương ứng, nếu không rớt về không-style.
- `origin_sheet_states` có sẵn trong `case` lúc gọi stepper? `co_case_status_view` đọc
  `case["products"][].origin_sheet_status` (`:281-284`) — products đã enrich ở context. Stepper hiện
  KHÔNG nhận products/sheet-states → cần truyền thêm vào `co_case_step_status` (đổi chữ ký, đụng mọi
  caller + test fakes — xem memory [[co-case-source-context-shapes]]).
- Test: `co_case_step_status`/`co_case_workflow_steps` là pure → dễ TDD. Kiểm grep test cũ assert
  "Preview"/"Cần soát"/status key để cập nhật. Static cache-bust CSS đăng ký 2 Jinja instance (memory
  [[static-asset-cache-busting]]) — class CSS mới không cần, chỉ css đổi nội dung.
- Đồng bộ màu: thêm `in_progress` (xanh dương) cạnh `active` (cũng tô primary) — đừng để bước đang
  xem (active) lẫn bước in_progress; active là viền+nền, status là màu chữ `em` → tách được.

## Open Questions

1. Bước 3 có hiển thị đếm "M/N chốt" ngay trên stepper không, hay chỉ nhãn trạng thái? (list page có
   progress bar; stepper chật hơn — đề xuất nhãn "Đang làm · M/N").
2. "Chứng từ" `ready` chỉ cần 1 file là tín hiệu yếu — có muốn siết theo loại chứng từ bắt buộc
   (BL/Invoice/Packing) không, hay để ngoài phạm vi B2?
3. Có gộp `review`+`preview` thành 1 (`attention`) luôn không, hay giữ 2 mức? (đề xuất gộp — 4 nhóm đủ).

## Next step

`/tdd` cho `co_case_step_status` + `co_case_workflow_steps`: viết test map (case fixtures → status
key + label) cho cả 5 bước, đặc biệt bước 3 theo `origin_sheet_states` (chưa có / đang làm / chốt
hết). Rồi implement (đổi chữ ký truyền sheet-states, thêm CSS `in_progress`/`done`, bỏ opacity-mờ +
dead wip), `/rev`, commit. Rủi ro trung bình, không phải refactor lớn — Phase 2 đã dọn sẵn nền.
