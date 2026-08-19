# Backlog

Durable backlog (survives handoffs — STATUS.md Next Steps is the prioritized slice). Items below
are captured, not yet scoped. Add `/discover` before non-trivial ones.

## Reconciliation 2026-07-17 (verified vs HEAD `f0095a7`, code = `dacb70d`)

Full re-verify of every open item against current code. **Paths moved** since most notes were written:
old `app/co_case.py` → `app/routers/co_case.py`; old `app/co_case_context.py` → `app/web/co_case_context.py`.
Verdicts (evidence at current paths):

| Item | Verdict | Note |
|---|---|---|
| DC3a | **CLOSED** | `1a9bc0f` (2026-07-06) added `is_bom_technical_noise` strip to `build_bom_proposal_rows` (`app/routers/co_case.py:2932`) |
| DC3c | **CLOSED** | hard-block belt for `lvc_declarable_unmatched`: calc-status (`routers/co_case.py:2111`), lock 409 (`web/co_case_context.py:1624`), export (`:1581`, `routers/co_case.py:1252`,`:1307`) |
| XX1 | **CLOSED** | VN-origin (#6–#13) shipped: `_resolve_vn_origin_lines` (`web/co_case_context.py:2732`), evidence store (mig 019 + `supplier_evidence_store.py` + `/clients/{id}/suppliers`), col M filled. **Col N/13 blank = user directive, not a bug** |
| DC2 | **CLOSED** | 4-tier name fallback + missing-name warning (`web/co_case_context.py:2600-2605`, `:2645`); source is materials-catalog `name`, not `catalog_candidates.sample_text` |
| #12 | **MOSTLY DONE** | per-material summed shortage renders (`case_shortfall_rollup` `web/co_case_context.py:2050`); only a single grand-total missing — semantically weak (mixed UOM), needs client input |
| B6 | **CLOSED (1 nit)** | FX toggle + missing-rate fallback correct (`fob_fx_source="missing"`, not 1.0). Nit: `bang_ke_renderer.py:185` double-applies rate on legacy rows lacking `_vnd` |
| D1 | **SHRUNK** | backstops added (`9f38afa` schema-version, `0f0812f`/#14 config-fingerprint). Remaining: delta-vs-full parity harness · `reason`/forced-full in refresh response · tombstone retry |
| LK1 | **SHRUNK** | `declarable_unmatched` block now CLOSED (=DC3c); endpoint rejects server-side (409, `routers/co_case.py:2248`); `origin_can_lock` formula unchanged. Remaining: **dirty-before-lock** (lock reads persisted case, no forced save/recalc → can lock stale data) |
| M1 | **OPEN (downgraded)** | both sub-bugs live. Sub-bug 1 no longer needs a DH API request — `get_bom_proposal` exists (`data_hub_client.py:440`) but 0 callers → CO-side wiring only. Sub-bug 2: `initOriginProposeBom` (`co_case.html:5687`) still re-POSTs |
| Fix F (D2) | **OPEN (narrow)** | overclaim guard nested in `if snapshot_exists:` (`co_stock_ledger.py:204`); cold-start (0 materialized rows) skips it |
| DC3b | **OPEN** | pre-mig-078 sheets stored materials without `customs_relevance` → junk kept (field absent → False) → leaks to export until re-Tính. Export is a pure renderer by design |
| ST1 | **OPEN** | guard-blocked sheets stay `bom_loaded` → badge "Đã nạp BOM"; no readiness chip added (deferred by ADR 2026-07-11) |
| P1-resid | **OPEN** | case-list index still N+1 `claims_summary_for_case` per dossier (`web/co_case_context.py:3494-3501`) |
| T1 | **OPEN** | `tests/conftest.py` has no schema isolation / `BARRY_DATABASE_SCHEMA` / teardown |
| FX1 | **OPEN** | `FORM_REFERENCES` still B/AI/CPTPP/EUR.1 only (`co_forms.py:9-42`); no Form X |
| EX1 | **OPEN (deferred)** | col K = decl-number only (`bang_ke_renderer.py:294`); no `import_ref_format` config — matches the "keep for now" decision |

**Design-park (no code-verify): RD3** (bảng kê "big change" content undecided) · **CS3** (2 parked items) ·
**D2 reservation-model** (decided: keep commit-time, don't build soft-reservation). **DH-side only: DC1**
(CO reads `customs_relevance`; needs DH re-ingest).

**Cross-item finding:** DC3b (pre-mig junk leak) and LK1 dirty-before-lock share one root — a sheet can be
locked/exported without a forced re-Tính, so stale materials (missing `customs_relevance`, or edited-but-unsaved)
reach the CO. One "force recalc before lock/export on stale/pre-mig sheets" fix would close both.

## Redesign luồng làm CO (khởi động 2026-06-14)

Rà lại toàn luồng 5 bước (Lô hàng → Chứng từ → Bảng kê C/O → TKX/TKN → Review & Xuất). User chủ
trương redesign từng bước. Ba điểm đã nêu trong phiên mở màn:

### RD1 — Bước 1: "chọn form" hầu như KHÔNG ảnh hưởng outcome (đã xác nhận bằng code 2026-06-14)
**DONE 2026-06-14 (committed `09509ae`).** User chọn phương án (a): bỏ form khỏi bước 1, chỉ giữ
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
**DONE 2026-06-14 (committed `09509ae`).** Dropzone async toàn diện: 7 slot card (kéo-thả + multi-file),
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
**PARTIAL — redesign overlay đã ship** (`2464797` Review dashboard ⇄ sheet Excel-like, deployed 0.14.0
`97dca73`; memory [[rd3-bangke-sheet-overlay]]). User báo còn **thay đổi lớn** nữa ở bảng kê — **nội
dung đó chưa chốt, note để phiên sau khai thác.** Vùng
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
**RE-SCOPED 2026-06-19 (verify code) — triệu chứng "luôn VND" KHÔNG còn đúng.** Hiện CÓ toggle native↔VND
chạy thật: `co_case_context.py:2319/2323` set `unit_value_native`/`material_value_native` = trị giá tồn thô,
`:2320/2324` set `*_vnd` qua FX (`:2288`); JS `co_case.html:3361-3399` đổi hiển thị theo `currency_mode`
(native / VND / cross-convert qua `fob_fx_rate`). Không có commit currency/FX server-side nào sau 2026-06-14.
**Việc còn lại = verify ĐỘ CHÍNH XÁC FX**, không phải sự tồn tại của toggle: cross-conversion `fob_fx_rate`
+ fallback khi thiếu rate (`co_case.html:3382`), nguồn rate (bcct_declared/customs_lookup). Added: 2026-06-14.

### B8 — Sheet đã chốt cần dễ nhận diện hơn (body + tabs)
**DONE 2026-06-14.** Thêm 🔒 vào status pill (toolbar + review row); tab đáy sheet locked: nền `--success-soft` + 🔒 + chữ status xanh; tab locked active viền/accent xanh (success) thay vì xanh primary; product-line panel locked viền dưới xanh. Vùng: `co_case.html` (pill + bottom-tab class) + CSS `.origin-sheet-tab-locked` / `[data-origin-sheet-locked]`.

### B7 — Dropdown "chỉ tiêu" (criteria) nền đen — làm elegant hơn
**DONE `cb3504b` (2026-06-18).** Native datalist đã được thay bằng **segmented picker** (`co_case.html:1277-1294`
`<div class="criteria-segments" data-criteria-segments>` + checkbox "hoặc Y" over hidden
`[data-origin-recommendation-criteria]` ở 1276) — hết dropdown nền đen. Legacy `<datalist id="origin-criteria-options">`
(co_case.html:844) giờ mồ côi (không còn `list=` nào trỏ tới), an toàn để xoá. Added: 2026-06-14.

## Tồn CO / Data Hub refresh

### D1 — Audit KỸ logic delta vs full + "refresh from Data Hub"
**PHẦN LỚN AUDIT ĐÃ XONG `2c856da` (2026-06-08, sau `039baeb`)** — "harden delta/full refresh against silent
tồn corruption": vá **(A)** force-full cho client aggregate, **(B)** server_time-before-pull, **(D)** empty-pull
wipe; + 13 test TDD (`tests/test_co_stock_empty_pull_guard.py`); chạm `_full_refresh`/`_plan_removed_keys`
(`co_case_context.py`), `co_stock_materializer.py`, `data_hub_client.py` (`bcct_server_time`).
**CÒN MỞ (hẹp, theo commit body 2c856da):** **(C)** tombstone retry / full backstop, **(E)** sync-status,
**(F)** refresh mode/reason UX, + **delta-vs-full parity harness**. Hạ cấp từ "audit toàn bộ" xuống các mục dưới.
Góc còn soi:
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
- **Vân tay wipe âm thầm (từ [[CS1]] 2026-06-14):** johnson-vn có lô mang cả `snapshot_row_added` (mới) lẫn
  `snapshot_row_updated` (cũ) mà KHÔNG có `snapshot_row_removed` → row bị xoá bởi đường không-emit-removed
  (nghi empty/partial-pull wipe trước guard `039baeb`, hoặc đường DELETE khác). **Query phát hiện drift:** bất
  kỳ lô nào `added` newer-than `updated`/`removed` đều là dấu re-derive → soi đường xoá còn sót.
Rủi ro: SAI TỒN (over/under-claim downstream). `/discover` + viết test parity trước khi sửa.
Added: 2026-06-07.

### D2 — Cross-dossier tồn contention: review 2026-07-08 (D vá xong · F còn mở)
**Bối cảnh:** review logic batch-flow khi làm NHIỀU hồ sơ / CÙNG 1 công ty (STATUS Next Steps #0).
Kết luận: cơ chế cốt lõi ĐÚNG — chốt cứng `record_sheet_lock` khoá `co_stock_rows FOR UPDATE` +
`net = remaining − Σ claims case/sheet KHÁC` → abort over-claim, sort `source_row` chống deadlock;
đường Tính/batch overlay `apply_used_qty(used_qty_by_lot)` nên preview đã net claims hồ sơ khác;
materializer upsert cùng thứ tự khoá + `_claims_blocking_removal` chặn xoá lô đang có claim.
- **D (VÁ XONG, uncommitted):** `/substitute-stock` (`co_case.py:~2553`) trước đây đọc snapshot thô,
  báo tồn **GROSS** (không trừ claims hồ sơ khác) → modal thay-NVL đánh lừa operator. Đã overlay
  `apply_used_qty` trước `case_allocation_pool` (mirror đường Tính). Test
  `tests/test_substitute_stock_claims_overlay.py` (2). KHÔNG gây over-claim (guard chốt vẫn chặn),
  chỉ là UX/hiển thị.
- **F (CÒN MỞ, hẹp):** cold-start — client CHƯA materialize (0 row `co_stock_rows`) → `record_sheet_lock`
  BỎ QUA check overclaim (`co_stock_ledger.py:198-204`, "trust allocator calculate-time" mà calc không
  khoá). ⇒ 2 hồ sơ có thể cùng chốt đè lô KHÔNG guard. Đòi client chưa refresh bao giờ → hiếm, nhưng
  là over-claim thật. Cân nhắc: chặn Chốt khi chưa có snapshot, HOẶC guard bằng nguồn BCCT trực tiếp.
- **E (note, an toàn):** `used_qty_by_lot` không lọc case → double-count claim CÙNG-case (conservative,
  under-state, không over-claim). Để nguyên.

**Reservation model (review 2026-07-08 PM2, câu hỏi "2 hồ sơ cùng tính 1 NVL"):** VERIFIED — claim chỉ
ghi ở CHỐT (`record_sheet_lock_claims` gọi từ `lock_co_case_origin_sheet:2214` + `bulk_lock_route:1880`);
chỉ 2 status `locked`/`released`, KHÔNG có `pending`/`reserved`. ⇒ **Tính-mà-chưa-chốt KHÔNG giữ tồn**;
hai bản nháp vô hình với nhau. Hệ quả:
- **Gap A** — "ai CHỐT trước thắng", không phải "ai tính trước": cả hai thấy A đủ (chưa ai lock) → xung đột
  lộ MUỘN ở Chốt (`StockOverclaimError`). `calculate-all` khuếch đại (tính+persist cả lô, 0 claim).
- **Gap B** — không re-evaluate: khi A rảnh lại (hồ sơ kia release/đổi trước lock), hồ sơ đã đổi NVL không
  được nhắc xem lại A; `material_override` là snapshot tại-thời-điểm, không tái-tối-ưu.
**Quyết định (khuyến nghị):** GIỮ commit-time; KHÔNG làm soft-reservation `pending`+TTL (tái tạo ghost-hold,
đổi schema, over-engineer cho tần suất thấp). Trị Gap A bằng **cảnh báo sớm read-only** ở bước Tính: đọc
calc-state các case OPEN khác cùng client (đường mining `origin_sheet_states` đã có ở `substitution_history.py`)
→ banner tư vấn "NVL A đang được hồ sơ X dự tính dùng". **Gộp vào Phase-2 pre-flight summary** (đừng mở feature
riêng). Ưu tiên: THẤP — contention hiện an toàn (guard Chốt chặn over-claim thật), đây là chống-lãng-phí-công.
Added: 2026-07-08.

## BOM / Propose (Data Hub)

### M1 — Propose BOM mới: trạng thái không sync + nút "Đã propose" propose lại
**RE-VERIFIED 2026-07-17 — CẢ HAI sub-bug CÒN NGUYÊN ở `f0095a7`; sub-bug 1 DOWNGRADED.** Update: a DH read
method `get_bom_proposal` now exists (`app/data_hub_client.py:440`) but has **0 callers** → sub-bug 1 no longer
needs a Data Hub API request, just CO-side wiring (poll/read status at render, adopt approved artifact). Sub-bug 2
handler `initOriginProposeBom` (`app/templates/co_case.html:5687`) still re-POSTs (sets `disabled` then
`finally` re-enables). Original note (refs pre-move to `app/routers/`/`app/web/`):
Flow Propose BOM mới: đã
**duyệt bên Data Hub** nhưng bảng kê CO vẫn hiển thị **"pending"/submitted**; và nút **"Đã propose ✓"** bấm
vào lại **propose lần nữa** (tạo proposal trùng). Hai lỗi tách biệt:

- **Status không refresh từ DH:** CO ghi `proposed_status = str(result.get("status") or "submitted")`
  (`co_case.py:2622`) và **không bao giờ đọc lại** trạng thái proposal từ Data Hub — `data_hub_client.py`
  KHÔNG có endpoint đọc proposal-status; `co_case_context.py:1265-1271` chỉ echo lại status đã lưu. DH
  duyệt xong, CO vẫn kẹt "pending". Cần: CO đọc trạng thái proposal hiện tại từ DH (poll / lúc render
  origin), khi `approved` thì phản ánh đúng (có thể adopt artifact đã duyệt làm BOM của sheet). Theo
  guardrail Data Hub: hợp đồng hiện tại chưa có endpoint → cần **API request artifact** (`.ai/api-requests/…`).
- **Nút "Đã propose" vẫn propose lại:** label đổi theo `product.origin_sheet_proposed_artifact_id`
  ("Đã propose ✓" vs "Lưu BOM mới", `co_case.html:1196`) nhưng handler `initOriginProposeBom`
  (`co_case.html:5406-5438`) **không disable/neutralize** nút khi đã proposed (chỉ có `confirm()`) → click
  lại POST `…/origin/sheet/{code}/propose-bom` lần nữa. Cần: khi đã proposed, đổi nút thành trạng thái/link
  (không re-POST), hoặc disable + chỉ cho "Lưu BOM mới" khi BOM thực sự đổi.

Pointers: write `proposed_status` (`co_case.py:2622`), label (`co_case.html:1196`), JS `initOriginProposeBom`
(`co_case.html:5406`), endpoint `…/origin/sheet/{product_code}/propose-bom`.
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
**RESOLVED 2026-07-17 (verified).** Name precedence for BOM rows (`app/web/co_case_context.py:2600-2605`):
`row.material_name` → `material.name` (DH materials catalog, `data_hub_client.py:1169`) → `stock.material_description`
(CO-stock/BCCT) → `stock_name_fallback`. Empty-name guard sets a warning + `material_name_missing` flag
(`:2645`, `:2685`). The fragile BOM-payload source is only tier 1; 4-tier fallback + warning backstop it.
Caveat: the catalog fallback reads materials-catalog `name`, NOT the `catalog_candidates.sample_text` the DH
brief cited — if that `name` is also empty the chain leans on CO-stock/BCCT. Original note below.

Brief DH (Finding 2) lưu: `hub.bom_artifact_rows.payload` = `{}` cho mọi mã `bom_observed`; tên thật
("Tube;Round;45#…", "Rendering;Semi-Assy") chỉ nằm trong `hub.catalog_candidates.sample_text`.
"Nếu CO đang hiển thị các tên này thì KHÔNG lấy từ payload dòng phẳng — cần xác nhận phía CO."
CO hiện có hiển thị các tên đó (thấy trong cases.json `material_description`). **Việc:** truy CO lấy
`material_description` từ field/endpoint nào cho mã `bom_observed`; nếu nguồn đó mất/đổi thì tên NVL
sẽ trống. Read-only điều tra, chưa khẩn. Added: 2026-06-09.

### DC3 — Hành vi dòng rác/đã-xoá qua Chốt/BOM/Xuất/Tính (cần chốt + vá)
Soi code 2026-06-09; **re-verify 2026-06-19** (DC3a/c còn mở, DC3b đã giảm nhẹ). Bảng hành vi
(dòng **đã-xoá** | dòng **rác** DH-classified):

- **(DC3a — DONE `1a9bc0f` 2026-07-06; verified 2026-07-17) Update BOM qua DH (propose-bom,
  `app/routers/co_case.py:build_bom_proposal_rows`):** decision chốt = YES strip. Now filters `deleted`
  AND calls `is_bom_technical_noise` (`:2932` `if not override.get("material_code") and is_bom_technical_noise(material): continue`)
  — proposed BOM matches the bảng kê. `sheet_edit_bom_rows` (recalc path) intentionally NOT changed (feeds
  the CO-internal sheet, not the DH proposal).
- **(DC3b — PARTIAL) Xuất + Tính (LVC/VNM/tồn):** đường **export GIỜ đã strip rác render-time** —
  `workbook_io.py:617`, `bang_ke_renderer.py:259`, `bang_ke_xml_generator.py:391` đều skip
  `is_bom_technical_noise(material)`. **NHƯNG vẫn phụ thuộc materials có `customs_relevance`:** sheet
  **đã-tính trước mig-078** lưu materials KHÔNG có field → `is_bom_technical_noise=False` → **rác LỌT
  vào export tới khi "Tính bảng kê" lại.** **Rủi ro còn:** phát hành C/O có rác trên sheet cũ. Cần:
  bắt buộc re-calc trước chốt/xuất, HOẶC render-time rebuild materials kèm `customs_relevance`.
- **(DC3c — DONE, belt shipped; verified 2026-07-17) `declarable_unmatched` cộng 0 → thổi LVC.** Now a
  triple hard-block belt (mirrors `missing_price`, "DC3c defense-in-depth"): flag `lvc_declarable_unmatched`
  (`app/web/co_case_context.py:3087`) → calc-status holds at `bom_loaded` (`app/routers/co_case.py:2111`) →
  lock 409 in `origin_sheet_action_error` (`co_case_context.py:1624`) → export blocker
  (`:1581` + `routers/co_case.py:1252`,`:1307`). No longer just a badge.

Liên quan [[DC1]] (gốc DH). Added: 2026-06-09.

## Bug — Bảng kê (origin)

### BG1 — Xoá 1 dòng NVL làm mất 2 dòng + fold count không tăng
**DONE 2026-06-14 (`60e55a1` + `1e089e9`, deployed 0.14.0 `97dca73`).** Gốc rễ: override map theo
**row-index hiển thị**; xoá **hard-remove** dòng khỏi `materials` → index dồn → recalc corrupt dòng kế
bên + fold-summary chỉ đếm override `deleted` mới nhất. Fix: **soft-delete** (giữ dòng, gắn cờ
`deleted`), calc chạy trên `active_materials` (`co_case_context.py:1774`); kèm unify UX xoá + Tính
contextual + cảnh báo Load BOM ghi đè. Memory [[bangke-soft-delete-index-model]].

<details><summary>Repro + giả thuyết gốc</summary>

Repro `growatt-vn/co-case-e44fe2065b62` → `/origin`:
1. Load BOM
2. Tính bảng kê (gốc **122 dòng**)
3. Xoá 1 dòng → tự lưu → view còn **120** (đáng lẽ **121**). Fold: "**1 dòng đã xoá**".
4. Xoá dòng nữa → còn **118** (đáng lẽ **120**). Fold vẫn "**1** dòng đã xoá" (đáng lẽ **2**).
5. Xoá dòng nữa → còn **116** (đáng lẽ **119**). Fold vẫn "**1** dòng đã xoá" (đáng lẽ **3**).

**Triệu chứng:** mỗi lần xoá 1 dòng, view giảm **2** dòng (122→120→118→116) thay vì 1; fold "đã xoá" **kẹt ở 1**, không cộng dồn. Tổng bảo toàn (view + fold) = 121 → 119 → 117 < 122 ⇒ **mất dòng thật** (1, rồi 3, rồi 5 dòng biến mất hẳn), không chỉ lỗi hiển thị. Nghiêm trọng: bảng kê thiếu NVL → sai LVC/VNM + sai BOM khi chốt.

**Giả thuyết (chưa điều tra):** staged-delete map sai index dòng (off-by-one giữa row-index hiển thị và override key), hoặc recalc/refold sau auto-save loại thêm 1 dòng (vd nhầm dòng kế bên là folded), hoặc fold-summary chỉ đếm override `deleted` mới-nhất thay vì cộng dồn. Cần soi `co_case_origin_sheet_save` + `sheet_edit_bom_rows` (recalc) + fold-summary render + JS `initSheetBulkDelete`/staged ops. Liên quan [[DC3]] (hành vi dòng đã-xoá), [[bangke-bulk-row-delete]].

</details>

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
- **P2 — fast `/calculate` giờ pull thêm catalog (2026-06-25).** Fix bảng-kê-trống (`#1A`) thêm
  `_material_catalog_rows` (`co_case.py`, ~13k NVL johnson, TTL 90s) vào fast path để có tên +
  `customs_relevance`. Đúng-đắn nhưng re-Tín nhích chậm vài giây ở lần đầu. **Tối ưu:** materialize
  sẵn `customs_relevance` + tên vào **snapshot tồn CO** (`co_stock_rows`/source snapshot) để fast path
  khỏi pull catalog riêng — khi đó fast `/calculate` chỉ đọc snapshot. Cần bàn shape snapshot + invalidation.

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

## Tồn CO — Lịch sử lot (UI)

### CS1 — Modal "Lịch sử lot tồn CO" khó hiểu + nghi duplicate dữ liệu
**REDESIGN DONE + COMMITTED `ca11c37` (2026-06-15, PR #2 `a295a7d`)** — chạm `co_stock.html` (+51),
`app.css`, e2e `.ai/scripts/e2e_cs1_lot_history.cjs`, tests. (Note "chưa commit" 2026-06-14 đã stale.)
Chỉ còn root-cause churn → [[D1]].
- **Điều tra — KHÔNG phải trùng:** events query theo lot-tuple `(decl,line,customs)`; materializer gắn
  `notes:materializer:<source_row>`. `_classify_changes` chỉ gán `added` khi row vắng trong snapshot → cùng
  1 source_row vừa `updated` (05-29) vừa `added` (06-07, *muộn hơn*) ⇒ row bị **xoá rồi nạp lại** giữa hai
  lần, không phải duplicate. Trên johnson-vn added mới hơn updated mà **không có** `snapshot_row_removed` ⇒
  xoá bởi đường KHÔNG emit removed = **vân tay wipe snapshot âm thầm** (thuộc [[D1]], đã vá một phần `039baeb`).
- **Redesign:** `fold_lot_events` gộp mọi `snapshot_row_*` thành **1 dòng "Hệ thống · nguồn"** (đếm
  thêm/cập-nhật/gỡ, cờ `readded`, net 0), **ghim cuối**, mờ bằng color token (không opacity); template thêm
  nhãn raw + hint header "Sự kiện"/"Δ". Verified data thật johnson-vn (3 sk→2 nhóm, readded=True) + screenshots
  `.ai/screenshots/2026-06-14-cs1-lot-history-modal/`, 0 console error. Test fold 14/14.
- **Còn lại:** root-cause churn (vì sao row bị xoá không-removed) = việc của [[D1]]; phần UI CS1 đã xong.

<details><summary>Báo cáo gốc (user)</summary>

Modal lot history (vd lot `107709127630 / dòng 7 / 1000490420`) header
"4 mục · gộp 20 sự kiện" nhưng bảng khó đọc đến mức chính dev cũng không hiểu:
- 2 dòng `system` cùng `materializer:import-row-a92652654de1f873` — một `snapshot_row_added`
  (2026-06-07) và một `snapshot_row_updated` (2026-05-29) — trông như **trùng**. Cần làm rõ vì sao
  1 import-row sinh cả added lẫn updated, 2 dòng này nghĩa gì với operator (có thực sự duplicate
  hay chỉ gộp/hiển thị nhầm).
- Cột "Δ tồn ròng" = "—" cho dòng system; cột "Sự kiện" hiện số đếm thô (1 / 17 (9 chốt·8 mở) / 1 / 1)
  không kèm giải thích → user không biết "17 sự kiện" nghĩa là gì.
- Trộn **sự kiện hệ thống** (materializer/snapshot) với **sự kiện nghiệp vụ** (import, claim_lock)
  trong cùng bảng, không phân tầng → nhiễu.

Việc: (1) điều tra vì sao materializer ghi cả added+updated cho cùng import-row (thật sự duplicate
hay không); (2) redesign bảng cho operator đọc được — tách/ẩn dòng hệ thống, diễn giải cột "Sự kiện",
Δ rõ ràng. Vùng: modal `co-stock-history-*` + nguồn lot history (co_stock ledger/materializer).

</details>

Added: 2026-06-14.

## Review Tồn CO — GỘP (consolidated 2026-06-14)

Umbrella gom mọi việc tồn CO. **State-machine khoá/đua = ĐÃ XONG** (Phase 1 bỏ mutex A + Phase 2 tách
Load BOM/Tính — verified: `grep origin_calculation_lock app/`=0; `FOR UPDATE` `co_stock_ledger.py:215`;
status `bom_loaded` + endpoint `/load-bom`; memory [[co-stock-lock-orthogonal-overclaim-race]]).
**Còn mở = review mô hình SỐ LIỆU tồn:** CS2 (decouple trừ-lùi, dưới) · D1 (delta-vs-full parity, chồng
finding C dưới) · CS1 (lịch sử lot = Phase 3 cũ) · DC3 (rác qua Chốt/Xuất).

### CS3 — Review TỔNG flow tồn CO: 3 nguồn (DH / import workbook / thay đổi từ CO cases)
**REVIEWED 2026-06-14 — brief `.ai/features/2026-06-14-cs3-costock-three-sources/brief.md`.** Kết luận:
KHÔNG có "nguồn tồn của client" tường minh — source-mode ngầm per-row (`payload.co_stock_source='workbook_snapshot'`)
+ `is_workbook_sourced()` EXISTS-1-dòng chặn TOÀN BỘ DH refresh; schema không cấm trạng thái lẫn (**R1 = SAI TỒN
tiềm tàng**). Claims orphan-safe (tốt, trực giao). **Hướng (user chỉ đạo 2026-06-14): TRUNG HOÀ cả 3 nguồn
per-lot — KHÔNG ép về 1 nguồn.** **Mô hình CHỐT:** 3 nguồn sở hữu 3 đại lượng riêng (DH=opening lô mới · workbook **ghi remaining
THẲNG**, off-app, `fold=False` · CO=tiêu hao), `tồn = remaining_import − CO_claims`; workbook off-app-only nên
CO trừ tiếp không trùng; khoá lô `(decl,line,customs)`. **Đường import standalone ĐÃ làm đúng model — KHÔNG
dùng `fold_baseline`, KHÔNG dính CS2 §A** (đừng lẫn 2 cơ chế: ① import standalone `fold=False` vs ② DH-overlay
cũ `fold_baseline` ôm P0). **Trạng thái 2026-06-15: LEGACY FOLD ĐÃ GỠ HẲN** (CS2 §A-E + bảng `co_stock_adjustments`
drop mig 017; full suite 591 pass) → còn một model duy nhất, hết nhầm fold-vs-direct. **CÒN PARK** (chưa cần):
(1) rule re-import configurable, (2) nới `is_workbook_sourced` cho DH thêm opening **lô mới** trên client đã chốt
workbook (hiện guard chặn DH toàn bộ). `/tdd` khi làm. Chi tiết: brief + [[cs3-costock-harmonize-model]].

<details><summary>Scoping gốc CS3</summary>

**REQUESTED 2026-06-14 (user).** Giờ tồn CO có **3 nguồn ghi vào `co_stock_rows`** — cần review hợp nhất,
tránh chồng/đè/loạn:
1. **Data Hub** — `_refresh_co_stock_delta_or_full` derive từ BCCT (fold=True, allocation per config).
2. **Import workbook (mới)** — `import_standard_snapshot` standalone, set thẳng (fold=False, remaining baked).
   Guard `is_workbook_sourced` chặn DH-refresh đè. [[co-stock-workbook-converter]].
3. **Thay đổi từ CO cases** — claim/lock/release (`co_stock_ledger`) overlay ở read; recalc/Chốt.
Câu hỏi: 3 nguồn này tương tác thế nào trên cùng 1 client? (vd client vừa có snapshot workbook vừa muốn
claim từ hồ sơ — ledger overlay đúng chưa; re-import có reset ledger không; client chuyển từ workbook
sang DH thì sao). Cần state model rõ "nguồn tồn hiện tại của client là gì".
**Minor từ /rev 2026-06-14 (gộp vào đây):** (a) `stock_rows_from_standard` source_row key theo (decl,line)
nhưng `parse_workbook` consolidate theo triplet (decl,line,customs_code) — nếu 1 (decl,line) có 2 prefix
thì collision (không xảy ra với NK2 per-lot, đã verify (decl,line) unique — nhưng nên đồng bộ khoá);
(b) workbook-sourced client KHÔNG DH-refresh được (by design, có message) — cân nhắc nút "chuyển sang DH";
(c) `convert-workbook` route `except Exception` trả raw exc cho operator (info-leak nhẹ, operator-only).
`/discover` trước. Added: 2026-06-14.

</details>

### CS2 — Review trừ-lùi + convert tool + decouple — REVIEW XONG (3-agent 2026-06-14); FOLD GỠ HẲN 2026-06-15
**Discovery cho CS2 coi như xong — findings dưới thay cho `/discover`.** 3 agent: sweep dependency +
review correctness fold + review convert tool.

**SHIPPED 2026-06-14 — CONVERTER add-on tool (user scoped: KHÔNG đụng DB).** Upload workbook trừ-lùi
`.xlsm` → convert sang **template chuẩn** (`co_stock_template`) → tải về. Ingest là việc user TỰ upload
template đó vào "Import tồn CO" sẵn có (convert ⊥ ingest). `co_stock_workbook.py`
(`parse_workbook`+`convert_to_standard_template`, no DB); route `POST /co-stock/convert-workbook`
(preview+base64, no write); UI panel "Chuyển đổi workbook trừ-lùi → template chuẩn" trên co_stock.html;
CLI `convert_co_stock.py` thành thin wrapper. **Deal được cả 2 client** (validated trên file thật:
Growatt 30.923 lô, Johnson 51.095 lô, 0 read error) — cùng layout NK2/Save.
**Hệ mã khác nhau (đã AUDIT + xử đúng):** converter key theo **prefix "#&" của tên hàng** (= BCCT
`customs_item_code` = khoá lô hệ thống), KHÔNG phải cột Mã NPL/SP. **Audit DB:** trừ-lùi name-prefix ==
BCCT customs_item_code 1500/1500; Mã NPL/SP == BCCT **0/1500** (Growatt) → nếu key theo Mã NPL/SP thì
overlay khớp 0 lô, "Đã xuất" không áp = SAI TỒN. Johnson prefix=Mã NPL/SP (trùng); Growatt prefix=category
"DIOT", Mã NPL/SP="008.x" là mã nội bộ/BOM (=allocation_code, không phải khoá lô). `matching_code()` =
split "#&" → prefix, fallback cột khi không có "#&". Validated: converted customs_code == BCCT 2000/2000
cả 2 client. Tests `test_co_stock_workbook.py` (file-mode), e2e `e2e_costock_workbook_snapshot.cjs` 11/11.
Memory [[co-stock-workbook-converter]].
(Đã thử rồi GỠ đường ingest-standalone `import_standard_snapshot`/`/co-stock/import-snapshot`/
materializer `fold=False` theo chỉ đạo "đừng đụng DB" — đừng thêm lại nếu không được yêu cầu.)

**DONE 2026-06-15 — FOLD GỠ HẲN** (user chỉ đạo "bỏ code legacy"; data test bỏ được nên KHÔNG cần parity net).
Xoá `fold_baseline`/`apply_adjustments`/`aggregate_by_lookup_key`/`refold_*`, bảng `co_stock_adjustments`
(mig 008 → drop **mig 017**), route `/co-stock/import` overlay (form co_stock.html repoint → `/import-snapshot`),
`app/co_stock_adjustments_store.py`, `scripts/fix_trului_unit.py`, test `test_co_stock_fold.py`. Off-app baseline
giờ CHỈ vào qua workbook import (`baseline_used_qty` bake thẳng); DH refresh = opening-only; read overlay
`apply_used_qty` giữ nguyên. Full suite **591 pass**; legacy route → 404; bảng dropped. **2 bug P0 (A) + findings
B-E dưới giờ MOOT** (không còn fold). [[co-stock-folded-remaining-model]] [[cs3-costock-harmonize-model]].

*(Findings A-E dưới đã MOOT sau khi gỡ fold 2026-06-15 — giữ lại làm lịch sử.)*

**A. Hai bug SAI TỒN trong fold HIỆN TẠI (chưa decouple đã sai):**
- **P0-1 — aggregate-policy fold double-count/phantom.** `refold_adjustment_lots`
  (`co_stock_materializer.py:177-191`) khớp adjustment ↔ snapshot row bằng key per-import-row
  `(import_declaration_no, line_no, customs_item_code)`. Với `lot_policy=aggregate_by_declaration_and_allocation_code`,
  `co_stock_rows` là LÔ GỘP (`line_no` "3,7,11", `bcct_qty`=SUM) → key không khớp → (a) adjustment
  KHÔNG fold (tồn ẢO: agency đã trừ, CO vẫn full) hoặc (b) khớp 1 segment → opening 1-dòng đè lên lô
  gộp → hỏng opening cả lô. Delta đã force-disable cho aggregate (`co_case_context.py:2987`) nhưng
  **import/refold KHÔNG có guard.** Lock guard đọc remaining lô gộp → mis-gate Chốt.
- **P0-2 — `bcct_qty` sticky invariant.** `fold_baseline` (`co_stock_adjustments_store.py:370-372`)
  idempotent CHỈ khi `bcct_qty` đúng (`bcct = bcct_qty or available_qty`). Path nào sửa `available_qty`
  TRƯỚC fold đầu → `bcct_qty` sai vĩnh viễn (re-fold không tự lành; chỉ full BCCT refresh cứu, delta thì
  không). Latent, chưa cháy.
- **P1:** `stock_available_qty` fallback `remaining_qty=="" → available_qty` (= full opening) =
  over-claim trap (`co_case_context.py:1718`); `void_batch` không tự refold
  (`co_stock_adjustments_store.py:330`); aggregate delta drift. **P2:** fold unit-blind (không guard kg
  vs MT — dựa `fix_trului_unit.py` vá data); deprecated `apply_adjustments` clamp 0 (sign khác model).

**B. DECOUPLE XOÁ P0-1, P0-2, P1(void), P1(delta-fold-drift), P2(sign) — đúng hướng, không chỉ là dọn.**
Còn trực giao (giữ nguyên dù decouple): P1 empty-fallback, P2 unit, race FOR UPDATE.

**C. Blast radius (verified line numbers) — 5 file lõi + scripts/tests:**
- `co_stock_adjustments_store.py` — XOÁ `fold_baseline:349-393`; deprecate/xoá `apply_adjustments:396-447`.
- `co_stock_materializer.py` — bỏ fold call `:106`, xoá `refold_adjustment_lots:157-212` + `refold_all_adjustments:215-224`.
- `co_stock_ledger.py` — REWRITE `apply_used_qty:570-601` (bỏ `+ baseline_used` → remaining = opening − ledger).
- `routers/co_stock.py` — REWRITE import `:262-306` (bỏ upsert+refold `:279/:293`), persist remaining thẳng.
- `web/co_case_context.py` — bỏ fold call `:347-356`.
- An toàn (plain consumer, không sửa logic): `co_stock_template.py`, `workbook_io.py:722`,
  `co_stock_events_store.py`, `routers/co_case.py:530` (chỉ sửa comment).
- Scripts: `fix_trului_unit.py` obsolete sau decouple (phụ thuộc BCCT join + refold); test `test_co_stock_fold.py`.

**D. Convert tool `scripts/convert_co_stock.py` CHƯA ĐỦ — KHÔNG dựng mới mà phải mở rộng.** Template chuẩn
(`co_stock_template.py`, 19 cột) KHÔNG có cột `remaining_qty`; phép trừ `opening − used` nằm HOÀN TOÀN
trong fold runtime. **Gỡ fold mà không sửa tool → `remaining = opening` (đúng bug tiền-fold = SAI TỒN).**
Cần (concrete):
  1. Thêm cột `remaining_qty` vào template + convert tính `remaining = opening − used` (signed; chốt policy âm=overclaim).
  2. Import persist remaining thẳng vào `co_stock_rows` (bỏ đường `co_stock_adjustments` + fold).
  3. Import MỌI lô — lật mặc-định skip zero-used (`convert.py:187`) vì BCCT không còn backfill opening.
  4. Chuyển chuẩn-hoá đơn vị (kg↔MT) VÀO convert (canonical unit lúc convert) — thay `fix_trului_unit.py` + `refold_all_adjustments`.
  5. Harden Save: sort event/lô trước consolidate (`_merge` lấy first-seen K, không sort) — hoặc chỉ hỗ trợ NK2.
  6. **Parity test BẮT BUỘC trước khi xoá fold:** workbook → convert → import → table, remaining == output fold cũ
     (real DB + workbook thật; file-mode = false green [[test-env-filemode-vs-datahub]]).
  7. UI upload+convert in-app (CS2 open) — hiện CLI-only; form `co_stock.html:56-72` chỉ nhận template đã-convert.

**E. Sequencing đề xuất (parity net TRƯỚC khi xoá lõi):** Stage 1 = template+convert+import tự-chứa
remaining + parity test xanh (GIỮ fold, fold chỉ xác nhận lại số) → Stage 2 = xoá fold 5 file lõi sau khi
parity chạy trên data thật PROD/DEMO. Tránh gutting lõi tồn chỉ với data test local.

<details><summary>Scoping gốc CS2 (giữ lại)</summary>

**REQUESTED 2026-06-14 (user).** Ba việc gộp; cần `/discover` trước (rủi ro: SAI TỒN downstream).

**(1) Review thật kỹ mô hình "folded-remaining".** `remaining = opening_qty (BCCT hoặc trừ-lùi
override) − baseline_used_qty ("Đã xuất" off-app) − live ledger`; fold tại materialize (refresh/import),
overlay ledger lúc read ([[co-stock-folded-remaining-model]]). Hàm gốc: `co_stock_adjustments_store.fold_baseline`
(`:349`, remaining SIGNED, idempotent re-fold từ `bcct_qty`). Điểm soi:
- **Dấu/đơn vị:** remaining âm hợp lệ? đơn vị kg vs metric-ton 1000× ([[trului-unit-mismatch-fold]], đã có
  `scripts/fix_trului_unit.py` — PROD/DEMO đã chạy chưa?).
- **Idempotency + parity delta-vs-full** (chồng [[D1]]): re-fold/re-import có hội tụ không, delta có lệch full theo thời gian.
- **NK2 vs Save:** Save = event log (sum-of-events) → overclaim risk; NK2 = reconciled per-lot. Logic chọn nguồn.
- **`apply_adjustments` DEPRECATED** (`:396`) còn dùng ở file-mode/tests — có nên dọn.

**(2) Tool convert workbook trừ-lùi → CO format — ĐÃ TỒN TẠI: `scripts/convert_co_stock.py`** (NK2/Save
của `tru-lui-co-template.xlsm` → standard CO stock template `app/co_stock_template.py` → import endpoint
`routers/co_stock.py`). Việc KHÔNG phải dựng mới mà: review/validate khớp workbook agency thật, harden
(missing key → `.errors.log`, `Đã_xuất=0` skip, `--include-zero-used`, consolidation triplet), tài liệu hoá
pipeline `workbook → convert → import → fold → materialize`. **Quyết:** có cần UI upload+convert in-app thay
script CLI không.

**(3) Sweep dependency trừ-lùi (đã liệt kê — `command grep -rniE "trừ.?lùi|tru[_-]?lui|trului"`):**
`co_stock_adjustments_store.py` (fold_baseline + deprecated apply_adjustments), `co_stock_materializer.py`
(:99/:158/:216/:536 fold + re-fold + backfill), `co_stock_ledger.py` (:183/:574-577 folded tồn),
`web/co_case_context.py` (:350/:3162 fold idempotent), `routers/co_case.py` (:530-539 recalc PHẢI từ snapshot
folded — [[co-stock-recalc-folded-parity]]), `routers/co_stock.py` (:156/:285/:395/:429 import+overlay),
`co_stock_template.py`, `workbook_io.py` (:722-723 HQ templates `tru-lui-co-output-template.xlsx`/`.xlsm`),
`scripts/fix_trului_unit.py`. Phân loại từng chỗ: **"embedded model" (cố ý, an toàn)** vs **landmine/ad-hoc
cần fix**.

**Hướng CHIẾN LƯỢC (user chốt 2026-06-14): DECOUPLE** — trừ-lùi thành data convert 1 lần (workbook →
standard CO stock qua `convert_co_stock.py`), **bỏ fold nhúng** (`fold_baseline` + re-fold ở materializer/
ledger/context/recalc/import), hệ thống chỉ dùng standard CO stock. Phạm vi lớn, đụng lõi tồn → `/discover`
kỹ + viết parity test trước khi gỡ fold (rủi ro SAI TỒN). AUDIT/HARDEN bị loại. Added: 2026-06-14.

</details>

## Bảng kê — Xuất xứ NVL

### XX1 — Input NVL CÓ xuất xứ (phụ lục X) → nhánh "có xuất xứ" của bảng kê (ảnh hưởng LVC/RVC)
**Status: SHIPPED 2026-07-12 via #6–#13; verified 2026-07-17 — col N/13 deferred by user directive.**
Per-row resolver `_resolve_vn_origin_lines` (`app/web/co_case_context.py:2732`): `qualifies = flag AND
is_vietnam_origin(origin_country)` → `origin_status='origin'`, excluded from VNM (`:2562`). Evidence store =
migration `019_co_supplier_evidence_events.sql` + `app/supplier_evidence_store.py` + curation screen
`/clients/{id}/suppliers` (`routers/pages.py:356`, `templates/suppliers.html`). Col M/12 filled
("Phụ lục X/<NCC>", `:2751`); col N/13 stays blank by directive. Remaining user-manual step: flag
Mingjie VN + Minghui VN on growatt-vn (STATUS Next Steps §000). **Original design note (kept for history):**
per-ROW resolver (`origin_country`→VN AND supplier flag), KHÔNG per-lot input tay; evidence store
CO-side `co_supplier_evidence_events` (không cần DH API request — dữ liệu đã đủ qua BCCT);
Growatt seed = 2 NCC (Mingjie/Minghui VN), Johnson = 0. Xem DECISIONS.md 2026-07-10/11 +
knowledge `2026-07-10-vn-origin-supplier-data-facts.md` (addendum 2026-07-11). Ticket order trong
session `2026-07-11-vn-origin-grill-part2-close.md`.
**REPORTED 2026-06-14 (user).** Hiện **đa số NVL = không xuất xứ** (mặc định bảo thủ
`origin_status='non_origin'`, source `default_conservative`). Nhưng có **lô nhập khẩu CÓ xuất xứ**
(kèm **phụ lục X** làm chứng từ). Cần:
1. **Cách input** dữ liệu xuất xứ: đánh dấu lô/NVL là `origin` (per-lot theo tờ khai nhập, hoặc per-material),
   gắn tham chiếu chứng từ phụ lục X.
2. Khi **tính bảng kê**: NVL đó vào **nhánh có xuất xứ** (`origin_status='origin'`) → **KHÔNG cộng vào VNM**
   (xem `origin_material_from_bom_row`: `vnm_value = material_value if origin_status=='non_origin'`) → **tăng
   LVC / giảm phần KXX** tương ứng (`calculate_lvc_result`).
3. **Nguồn dữ liệu:** ưu tiên Data Hub (BCCT/customs có field xuất xứ?) — theo guardrail DH, kiểm
   `app/data_hub_client.py` trước; nếu hợp đồng chưa có field origin per-lot thì viết API request artifact.
   Fallback: input tay trên CO + lưu override per-material (giống `material_overrides`).

**Bảng kê cột M-N (note 2026-06-18, user):** cột **M** = "C/O ưu đãi nhập khẩu/ Bản khai báo của nhà
SX/ NCC NVL trong nước" (số) + **N** = "Ngày" là chỗ khai chứng từ xuất xứ ưu đãi cho **NVL CÓ xuất xứ**.
Renderer trước đây nhét nhầm `source_document_ref`/`source_document_date` vào đây (demo lòi ra "Seed import
row 1/3") → **ĐÃ blank tạm** ở cả 2 path: config `app/bang_ke_renderer.py` (`co_doc_no`/`co_doc_date`) +
legacy `app/workbook_io.py` (`co_no`/`co_date`). **Khi làm XX1:** điền M-N từ chứng từ xuất xứ ưu đãi
(phụ lục X / C/O nhập / bản khai NCC) của lô NVL `origin` — KHÔNG dùng lại source_document_ref.

Vùng: `origin_status_details_from_material` (phân loại xuất xứ), `material_overrides` (nếu input tay),
template cột "Xuất xứ" + chứng từ phụ lục X. Liên quan [[technical-flattened-export-noise]] (customs_relevance
là trục KHÁC — declarability, không phải origin). `/discover` trước. Added: 2026-06-14.

### LK1 — Review logic "Chốt" (lock) bảng kê: khi nào lock-able?
**PHẦN GUARD HẸP ĐÃ XONG 2026-06-19** (`66d5ad7` empty/no-BOM #13c + `0e7128a` missing-price) — bổ sung
gating trong `origin_can_lock` (`co_case_context.py:1306-1313`); chưa có commit nào chạm `origin_can_lock`
sau `0e7128a`. **Còn lại = review RỘNG** (chưa có artifact) các điểm dưới; có thể đóng-as-covered phần đã vá.
Hiện trạng (code): `origin_can_lock = code and status=='calculated' and not sequence_reason`;
endpoint lock guard qua `origin_sheet_action_error` + `reject_if_sheet_locked`. Điểm cần soi:
- Chỉ `calculated` mới chốt được — nhưng sheet đang có **chỉnh sửa chưa lưu** (pending ops client) thì
  sao? Chốt khi đang dirty = chốt dữ liệu cũ → cần buộc lưu/tính trước.
- `sequence_reason` (phải chốt theo thứ tự sheet trước→sau): đúng/đủ chưa?
- Sheet `stale` (cần tính lại) KHÔNG chốt được (đúng) — UI có chặn rõ + giải thích không.
- ~~Còn dòng `declarable_unmatched` / chưa khớp tồn → có nên **chặn cứng** chốt?~~ **DONE (=DC3c, verified
  2026-07-17)** — now hard-blocks at lock (`origin_sheet_action_error` 409) + export.
- **Endpoint reject: CONFIRMED server-side (verified 2026-07-17)** — `lock_co_case_origin_sheet`
  (`app/routers/co_case.py:2248`) calls `origin_sheet_action_error` → HTTP 409 (`:2253`); edits guarded by
  `reject_if_sheet_locked` (`:893`). Not just a disabled button.
- **Dirty-before-lock: STILL OPEN (verified 2026-07-17)** — lock reads the PERSISTED case
  (`routers/co_case.py:2264-2272`), no forced save/recalc → a sheet with unsaved client edits, or a stale
  sheet, can be locked against last-saved data. Only re-validation is the StockOverclaim pre-check (`:2273`).
  Shares a root with [[DC3]] DC3b — see Reconciliation cross-item finding.
Vùng: `origin_can_lock` / `origin_sheet_action_error` (`co_case_context.py`), lock endpoint (`co_case.py`),
nút Chốt (`co_case.html`). Liên quan [[DC3]]. `/discover` trước. Added: 2026-06-14.

## Bảng kê — Định dạng cột

### EX1 — Configurable định dạng tham chiếu tờ khai ở cột K (số vs số/dòng)
**Note 2026-06-18 (user).** Cột **K** bảng kê = "Tờ khai hải quan nhập khẩu/HĐ GTGT" (Số). **AUDIT template**
(`form-mau-combined.xlsx`, đọc trực tiếp): khối tờ khai = merged **K12:L13** → form chỉ có **K (Số) + L
(Ngày)**; **"dòng hàng" ở cột O là HELPER ẨN** (`hidden=True`) và **ngoài `print_area` (A:N)** → KHÔNG hiển
thị/in. Data mẫu template: K = chỉ số TK (`108097982530;`), dòng (`2;`) chỉ ở O ẩn. **Quyết (user): tạm thời
giữ K = chỉ số tờ khai** (khớp form gốc; export hiện đã đúng vậy — `import_decl_no→K`, dòng ở O ẩn).
**Về sau: làm CONFIGURABLE** — tuỳ client/form chọn K hiển thị `"số"` hay `"số/dòng"` (vd `108097982530/2`)
vì form không có cột dòng riêng. Vùng: `bang_ke_renderer.py` (`import_decl_no→K`, có sẵn `import_line_no`),
config `config/bang-ke-forms/*.json` (cân nhắc field `import_ref_format: number|number_line`); cũng cân nhắc
dấu nối nhiều TK/dòng (template gốc dùng `;`, renderer hiện dùng `, `). Cột L (Ngày) đã wire sẵn (auto từ
`registration_date` lô). Added: 2026-06-18.

## CO Forms

### FX1 — Form X (VCCI non-preferential) thiếu trong `app/co_forms.py`
**FOUND 2026-07-11 (trừ-lùi workbook scan).** Workbook agency có sheet `FORM X` — template C/O
không ưu đãi thứ hai của VCCI (bên cạnh `FORM B`), đã dùng thật (consignor CAIXIANG → RONGBAOYU,
reference number 51400641). `app/co_forms.py` chỉ model B/AI/CPTPP/EUR.1 → parity gap nhỏ.
Forms config đã extensible qua `load_co_form_config` (`/settings/co-forms` UI) nên có thể thêm
qua config trước, `FORM_REFERENCES` built-in sau. KHÔNG liên quan cumulation; phase-2 in-bloc
đã defer-until-demand (DECISIONS.md 2026-07-11). Added: 2026-07-11.

## Trạng thái sheet — badge honesty

### ST1 — "Tính tồn tất cả" xong, sheet bị guard chặn vẫn hiện "Đã nạp BOM" (readiness chip đã defer ở ADR 2026-07-11)
**User catch 2026-07-12** (screenshot `.ai/screenshots/2026-07-12-vn-origin-e2e/18-furniture-summary-calculated.png`):
chạy batch "Tính tồn tất cả (SP)" xong, số liệu (LVC, trị giá, phân bổ) đã tính + LƯU đầy đủ,
nhưng cột TRẠNG THÁI vẫn "Đã nạp BOM". Cơ chế: `calculate-all` gán status qua
`calculated_sheet_status` (`co_case.py:2038`) — sheet dính guard (thiếu tồn `lvc_allocation_shortage`
(#8), thiếu đơn giá, `declarable_unmatched`, missing_bom) GIỮ ở `bom_loaded` để không chốt/xuất được.
Đúng theo thiết kế guard, nhưng label GỘP 2 nghĩa: "chưa tính" và "đã tính nhưng bị chặn" — user
nhìn batch chạy xong mà tưởng chưa chạy. ĐÃ CÓ ADR: "[2026-07-11] Status model: badge honesty via
a readiness chip, NOT by re-keying the status enum (deferred)" — spec VN-origin cũng pin
"Status-enum refactor / readiness-chip work" ngoài scope. Enhancement đề xuất: giữ status enum
nguyên (an toàn cho save-route hardcode + guards), thêm CHIP readiness cạnh badge cho sheet
`bom_loaded`-có-số-liệu: "Đã tính — chặn chốt: thiếu tồn N dòng" (nguồn: `lvc_allocation_shortage`
/ `lvc_missing_price` / `lvc_declarable_unmatched` / `missing_bom` + `origin_lock_block_reason`
đã có sẵn per-product). Vùng: summary table + sheet tab pill (`co_case.html`), context đã có đủ
cờ — chỉ là render. KHÔNG đổi `calculated_sheet_status`. Added: 2026-07-12.
