# Backlog

Durable backlog (survives handoffs — STATUS.md Next Steps is the prioritized slice). Items below
are captured, not yet scoped. Add `/discover` before non-trivial ones.

## Redesign luồng làm CO (khởi động 2026-06-14)

Rà lại toàn luồng 5 bước (Lô hàng → Chứng từ → Bảng kê C/O → TKX/TKN → Review & Xuất). User chủ
trương redesign từng bước. Ba điểm đã nêu trong phiên mở màn:

### RD1 — Bước 1: "chọn form" hầu như KHÔNG ảnh hưởng outcome (đã xác nhận bằng code 2026-06-14)
**DONE 2026-06-14 (uncommitted→local).** User chọn phương án (a): bỏ form khỏi bước 1, chỉ giữ
market. Đã bỏ block "Form gợi ý" (modal tạo + Lô hàng), macro chết `form_lane_matrix()`, và 3 thẻ
form-lanes trong preview invoice (server + JS) — giữ "Gợi ý thị trường" + nút "Dùng thị trường";
`co_form_type` vẫn auto-suy ngầm từ market. Dọn CSS mồ côi (`.form-lane*`/`.mini-rule-list*`/
`.invoice-form-hints*`) + context key `form_lanes`. Verified e2e (form-preview=0, form-hints=0).

`co_form_type` cấp-case (set ở bước Lô hàng) là **label trang trí**: chỉ lưu trên case
(`co_case_store`/`workflow_state_store`), round-trip trong workbook nội bộ (`workbook_io.py:112/187`),
và hiển thị ở list/header. **Không vào calc bảng kê, không chọn template export HQ.** Bằng chứng:
- Form thực sự chi phối outcome là **per-sheet** `origin_sheet_effective_form_code` ở **bước 3** =
  `form_override (config bar) or sheet_form_recommendation(market, finished_hs)`
  (`co_case_context.py:1190, 1179`). Recommendation suy từ **destination_market** + finished_hs —
  KHÔNG đọc `co_form_type`.
- Template export HQ rẽ nhánh theo per-sheet form (`workbook_io.py:441`: EUR.1 → Phụ lục VII/PSR;
  còn lại → LVC). Tiêu chí/ngưỡng calc cũng per-sheet (`effective_criteria` + LVC/RVC threshold).
- Ở bước 1, form chỉ là **preview** của recommendation: hidden input auto-fill từ
  `recommended_form_lane.display_name` (`co_case.html:520/655/958`), không có picker bind downstream.
  Input bước 1 thật sự có nghĩa = **destination_market**.
**Quyết định cần chốt:** (a) bỏ hẳn "chọn form" ở bước 1 — chỉ chọn market, để form nổi lên như gợi
ý/đối tượng override ở bước 3; HOẶC (b) cho form bước 1 thành default THẬT cho sheet (bind vào
`effective_form`). Hiện trạng "lưng chừng" (set nhưng không bind) chính là lý do thấy vô nghĩa.

### RD2 — Bước 2: redesign UI upload chứng từ ("nhìn cứ sao sao")
**DONE 2026-06-14 (uncommitted→local).** Dropzone async toàn diện: 7 slot card (kéo-thả + multi-file),
upload XHR có progress bar không reload, chip file (ext·tên·size·×), xoá inline, counter "Bắt buộc
N/3 · Bổ sung N"; bỏ ô invoice/BL lặp. Backend: `delete_supporting_file` + route DELETE + POST
content-negotiate JSON khi async (giữ 303 no-JS). CSS Primer `.doc-*` thay sạch `.document-*`/
`.upload-form-inline`. e2e `.ai/scripts/e2e_documents_flow.cjs` 13/13 pass, no console error.

Hiện trạng (`co_case.html:672-765`): 7 slot (3 bắt buộc BL/Invoice/Packing + 4 bổ sung), **mỗi slot
là một `<form multipart>` riêng, page-reload mỗi lần upload** (`hx-boost="false"`), 1 file/lần, không
drag-drop, không progress. Mỗi slot bắt buộc còn lặp lại 2 ô `invoice_no`/`bill_of_lading_no` (trùng
dữ liệu shipment đã có trên case) → nhiễu. Hướng đề xuất: dropzone gom drag-drop + multi-file +
upload async (không reload, theo pattern background export đã có), bỏ ô invoice/BL lặp (lấy từ
shipment, chỉ hỏi khi override), checklist tiến độ rõ (vd "2/3 bắt buộc"), list file có icon/size/xoá.
Bám design Primer [[ui-design-direction-primer]], tránh opacity-muted text [[css-no-opacity-muted-text]].

### RD3 — Bước 3: bảng kê C/O — THAY ĐỔI LỚN (chi tiết phiên sau)
User báo sẽ có thay đổi lớn ở bảng kê. **Nội dung chưa chốt — note để phiên sau khai thác.** Vùng
liên quan đang mở: save-model decision [[bangke-excel-like-dirty-undo]] (Excel-like dirty/undo),
DC3 (hành vi rác/đã-xoá qua Chốt/BOM/Xuất/Tính), declarability [[technical-flattened-export-noise]].
Khi vào việc: `/discover` trước, đây là bước nặng nhất của luồng.

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

### B5 — Flash/toast notification khó nhìn + quá nhanh
**DONE 2026-06-14.** Gốc rễ "trong suốt": `.ui-toast` dùng `background: var(--surface)` — **token không tồn tại** → nền transparent. Fix: nền `var(--card)` (đặc), chuyển `.ui-toast-stack` xuống **góc dưới-phải**, viền trái 4px theo kind (success/error), font 0.9rem line-height 1.35, timeout **2600ms→5000ms**, keyframe trượt từ dưới lên. Vùng: `co_case.html` `toast()` + CSS `.ui-toast*` (`app.css`).

### B6 — Logic "nguyên tệ" (native currency) cần review kỹ
**REPORTED 2026-06-14 (user).** Các hồ sơ sofar **chỉ thấy hiển thị VND**, chưa lần nào thấy đơn vị tiền tệ khác → nghi `currency_mode='native'` / cột đơn giá-trị giá luôn rơi về VND. Cần review: nguồn `product.currency`/`fob_currency`/`unit_value_native` vs `unit_value_vnd`, đường FX (bcct_declared/customs_lookup), và `currency_mode` toggle có thực sự đổi hiển thị không. Vùng: `co_case_context` (đính giá/FX) + template cột đơn giá/trị giá + `_display_currency`. Added: 2026-06-14.

### B8 — Sheet đã chốt cần dễ nhận diện hơn (body + tabs)
**DONE 2026-06-14.** Thêm 🔒 vào status pill (toolbar + review row); tab đáy sheet locked: nền `--success-soft` + 🔒 + chữ status xanh; tab locked active viền/accent xanh (success) thay vì xanh primary; product-line panel locked viền dưới xanh. Vùng: `co_case.html` (pill + bottom-tab class) + CSS `.origin-sheet-tab-locked` / `[data-origin-sheet-locked]`.

### B7 — Dropdown "chỉ tiêu" (criteria) nền đen — làm elegant hơn
**REPORTED 2026-06-14 (user).** Ô "Tiêu chí" (`<input list="origin-criteria-options">` datalist trong ⚙ modal) bung dropdown **nền đen vô duyên**. Datalist native khó style cross-browser → cân nhắc thay bằng `<select>`/combobox tự dựng có style Primer, hoặc chỉnh token. Vùng: `co_case.html` `origin-criteria-options` + `[data-origin-recommendation-criteria]` + CSS. Added: 2026-06-14.

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

## BOM / Propose (Data Hub)

### M1 — Propose BOM mới: trạng thái không sync + nút "Đã propose" propose lại
Flow Propose BOM mới: đã **duyệt bên Data Hub** nhưng bảng kê CO vẫn hiển thị **"pending"/submitted**;
và nút **"Đã propose ✓"** bấm vào lại **propose lần nữa** (tạo proposal trùng). Hai lỗi tách biệt:

- **Status không refresh từ DH:** CO ghi `origin_sheet_proposed_status` lúc propose = `'submitted'`
  (`co_case.html:1206` `… or 'submitted'`) và **không bao giờ đọc lại** trạng thái proposal từ Data Hub
  → DH duyệt xong, CO vẫn kẹt "pending". Cần: CO đọc trạng thái proposal hiện tại từ DH (poll / lúc
  render origin) và khi `approved` thì phản ánh đúng (có thể adopt artifact đã duyệt làm BOM của sheet).
  Theo guardrail Data Hub: kiểm `app/data_hub_client.py` trước — nếu hợp đồng hiện tại chưa có endpoint
  đọc trạng thái proposal thì cần **API request artifact** (`.ai/api-requests/…`) trước khi build CO.
- **Nút "Đã propose" vẫn propose lại:** label đổi theo `product.origin_sheet_proposed_artifact_id`
  ("Đã propose ✓" vs "Lưu BOM mới", `co_case.html:1169`) nhưng handler `initOriginProposeBom`
  (`co_case.html:4902`) **không disable/neutralize** nút khi đã proposed → click lại POST
  `…/origin/sheet/{code}/propose-bom` lần nữa. Cần: khi đã proposed, đổi nút thành trạng thái/link
  (không re-POST), hoặc disable + chỉ cho "Lưu BOM mới" khi BOM thực sự đổi.

Pointers: template `co_case.html:1165-1206` (nút + dòng "Đã propose: <artifact> · trạng thái …"),
JS `initOriginProposeBom` (`co_case.html:4902`), endpoint `…/origin/sheet/{product_code}/propose-bom`.
`/discover` trước (đụng hợp đồng Data Hub). Added: 2026-06-08.

## Declarability (DH customs_relevance)

### DC1 — Johnson "rác" chưa tự loại/gộp: DH thiếu nhãn (gốc = ingest bỏ Material Group)
CO đã đọc `customs_relevance` + bỏ heuristic (phương án B) → chỉ loại/gộp dòng DH gắn
`excluded_non_material`. Nhưng rác thật của johnson (bản vẽ/checklist/nhãn — nhóm
`bom_observed`, 1.207 mã) đang `customs_relevance=null` → CO **giữ** (đúng B) → **không có gì
để gộp/loại tự động**. Vì vậy fold + auto-exclude hiện trống trên sheet johnson; chỉ chạy khi
operator **xoá tay** (đã hoạt động — xem screenshots) hoặc DH gắn nhãn xong.
**Gốc rễ (brief DH `data-hub/.ai/features/2026-06-08-leaf-nvl-declarability/brief.md`):** adapter
ingest (`sap_indented_walk.py`) chỉ giữ level/qty/unit/description, **vứt cột SAP `Material Group`
+ cờ `Phantom`/`Bulk`**; `customs_relevance` suy từ Material Group nên null. mig 078 re-ingest MG
(decode đúng: RD07=drawings, RD08=documents, RD12=labels) **nhưng chưa phủ hết nhóm
`bom_observed`-only** cho johnson. Đã gửi note sang DH liệt kê 25 mã:
`.ai/api-requests/2026-06-09-johnson-bom-material-group-gap.md` (+ copy ở
`data-hub/.ai/sister-app-notes/`). **Việc cần (DH):** chạy nốt re-ingest Material Group cho
`bom_observed`, KHÔNG map tay từng mã. CO không cần đổi code (đã đọc field). Added: 2026-06-09.

### DC2 — Xác nhận CO lấy tên NVL kỹ thuật từ đâu (brief DH cảnh báo)
Brief DH (Finding 2) lưu: `hub.bom_artifact_rows.payload` = `{}` cho mọi mã `bom_observed`; tên thật
("Tube;Round;45#…", "Rendering;Semi-Assy") chỉ nằm trong `hub.catalog_candidates.sample_text`.
"Nếu CO đang hiển thị các tên này thì KHÔNG lấy từ payload dòng phẳng — cần xác nhận phía CO."
CO hiện có hiển thị các tên đó (thấy trong cases.json `material_description`). **Việc:** truy CO lấy
`material_description` từ field/endpoint nào cho mã `bom_observed`; nếu nguồn đó mất/đổi thì tên NVL
sẽ trống. Read-only điều tra, chưa khẩn. Added: 2026-06-09.

### DC3 — Hành vi dòng rác/đã-xoá qua Chốt/BOM/Xuất/Tính (cần chốt + vá)
Soi code 2026-06-09. Bảng hành vi (dòng **đã-xoá** | dòng **rác** DH-classified):

- **Update BOM qua DH (propose-bom, `co_case.py:build_bom_proposal_rows:2224`):** loại `deleted`
  | **GIỮ rác.** Cố ý: BOM = cấu trúc sản phẩm, rác là thành phần BOM thật, `customs_relevance` chỉ
  chi phối bảng kê. **Quyết định cần user chốt:** có muốn update-BOM cũng strip rác không? Nếu có,
  thêm `or is_bom_technical_noise(...)` ở `build_bom_proposal_rows` (và cân nhắc `sheet_edit_bom_rows`).
- **Xuất + Tính (LVC/VNM/tồn):** loại đã-xoá (`sheet_edit_bom_rows:594` bỏ khỏi recalc), rác trung-tính
  (không phân bổ → trị giá 0, không claim tồn) | **NHƯNG chỉ đúng khi materials có `customs_relevance`.**
  Sheet **đã-tính-từ-trước** lưu materials KHÔNG có field → `is_bom_technical_noise=False` → **rác LỌT
  vào export + vào BOM** tới khi "Tính bảng kê" lại. **Rủi ro:** phát hành C/O có rác trên sheet cũ.
  Cần: bắt buộc re-calc trước chốt/xuất, HOẶC render-time rebuild materials kèm `customs_relevance`.
- **`declarable_unmatched` cộng 0 → thổi LVC** (thiếu trị giá không-xuất-xứ vì chưa khớp tồn). Spec Edit 5
  đề xuất **chặn/cảnh báo phát hành** khi còn dòng chưa khớp; hiện mới có **cảnh báo hiển thị** (badge +
  summary "cần đối soát"), **chưa chặn cứng** lúc Chốt/Xuất. Cân nhắc block phát hành C/O.

Liên quan [[DC1]] (gốc DH). Added: 2026-06-09.

## Bug — Bảng kê (origin)

### BG1 — Xoá 1 dòng NVL làm mất 2 dòng + fold count không tăng
**REPORTED 2026-06-14 (user).** Repro `growatt-vn/co-case-e44fe2065b62` → `/origin`:
1. Load BOM
2. Tính bảng kê (gốc **122 dòng**)
3. Xoá 1 dòng → tự lưu → view còn **120** (đáng lẽ **121**). Fold: "**1 dòng đã xoá**".
4. Xoá dòng nữa → còn **118** (đáng lẽ **120**). Fold vẫn "**1** dòng đã xoá" (đáng lẽ **2**).
5. Xoá dòng nữa → còn **116** (đáng lẽ **119**). Fold vẫn "**1** dòng đã xoá" (đáng lẽ **3**).

**Triệu chứng:** mỗi lần xoá 1 dòng, view giảm **2** dòng (122→120→118→116) thay vì 1; fold "đã xoá" **kẹt ở 1**, không cộng dồn. Tổng bảo toàn (view + fold) = 121 → 119 → 117 < 122 ⇒ **mất dòng thật** (1, rồi 3, rồi 5 dòng biến mất hẳn), không chỉ lỗi hiển thị. Nghiêm trọng: bảng kê thiếu NVL → sai LVC/VNM + sai BOM khi chốt.

**Giả thuyết (chưa điều tra):** staged-delete map sai index dòng (off-by-one giữa row-index hiển thị và override key), hoặc recalc/refold sau auto-save loại thêm 1 dòng (vd nhầm dòng kế bên là folded), hoặc fold-summary chỉ đếm override `deleted` mới-nhất thay vì cộng dồn. Cần soi `co_case_origin_sheet_save` + `sheet_edit_bom_rows` (recalc) + fold-summary render + JS `initSheetBulkDelete`/staged ops. Liên quan [[DC3]] (hành vi dòng đã-xoá), [[bangke-bulk-row-delete]].

Added: 2026-06-14.

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
