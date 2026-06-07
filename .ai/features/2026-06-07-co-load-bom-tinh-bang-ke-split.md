# Feature: Tách "Load BOM" (cấu trúc) khỏi "Tính bảng kê" (phân bổ tồn) — Phase 2

Discovery brief. Chưa code. Nối tiếp `.ai/features/2026-06-07-co-stock-state-machine-detangle.md`
(Scope Phase 2). Phase 1 (bỏ mutex A + FOR UPDATE) đã xong trên `co-stock-detangle-phase1`, chưa merge.

## Vấn đề (đã xác minh trong code)

Hôm nay vòng đời 1 sheet có 2 trạng thái hữu dụng:
- **shell** (`build_*` ở `co_case_context.py:860` → `origin_product_shell_from_invoice_match:993`):
  product `materials: []`, status `draft`, `mode_note` = "bấm Load BOM … để tính NVL và tồn CO".
- **calculated**: bấm **một** nút "Load BOM" (`co_case.html:1135`) bắn `POST …/calculate`
  (`co_case.py:1451`) làm **4 việc cùng lúc**: (a) refresh + đọc tồn (`_calculate_stock_rows_from_snapshot`,
  1-2s khi BCCT yên, 30-45s khi phải pull DH), (b) `prepare_case_origin_sheet` khai triển BOM +
  phân bổ tồn + tính VNM/LVC, (c) `set_origin_sheet_status(calculated)`, (d) `mark_origin_sheets_stale`
  cascade các sheet sau, (e) xoá `material_overrides` của sheet đích (1549-1551).

Không có cách nạp công thức NVL để **xem/sửa** mà không chạy cả phân bổ tồn nặng. Nhãn nút và message
("Đã load BOM vào bảng kê") đã chồng nghĩa với "tính".

**Fusion nằm ở đâu:** `origin_material_from_bom_row` (`co_case_context.py:1824`) trộn trong **một dict**:
- *Cấu trúc* (không cần tồn): `material_code`, `material_sequence`, `material_description`, `hs_code`,
  `origin_status*` (từ danh mục NVL), `consumed_qty = export_quantity × qty_per`, `bom_qty_per`,
  `bom_scrap_rate`, `bom_source`, `uom`, `fallback_unit_value` (đơn giá BOM/danh mục).
- *Phân bổ* (cần tồn): `allocation_lines`, `material_value*`, `non_origin_cif_value*`, `available_qty`,
  `valuation_status`, `allocation_status`, `allocation_shortage_*`, cảnh báo "thiếu tồn".

## Phát hiện then chốt cho thiết kế

1. **Override key theo *chỉ số dòng material*** (`sheet_edit_bom_rows:579`, `edit-row:2173`,
   `add-row`, `save:2293`). ⇒ Load BOM **bắt buộc** khai triển ra `product.materials` để override
   định vị được. Materials rỗng = không sửa được.
2. **Hạ tầng "sửa-không-allocate" đã có sẵn:** `edit-row`/`add-row` chỉ ghi override + set status
   **`stale`**, KHÔNG chạy phân bổ. `save` ghi override rồi `recalculate_origin_sheet_edits` (CÓ phân
   bổ) → `calculated`. Nên model "biên tập cấu trúc rồi tính sau" đã tồn tại; Phase 2 chỉ thêm cách
   tạo lần khai triển **đầu tiên** mà không allocate.
3. **`sheet_edit_bom_rows` đọc các field cấu trúc** (`bom_qty_per`, `uom`, `material_description`,
   `hs_code`, `unit_value`) từ material dict. Material khai triển cấu-trúc-only đã đủ field này
   (chỉ `unit_value` rỗng) ⇒ override + Tính-sau hoạt động không cần sửa.
4. **Không có Enum status cứng** — chỉ dict `ORIGIN_SHEET_STATUS_LABELS` (`co_case_context.py:32`) +
   `set_origin_sheet_status` rơi về `draft` nếu status lạ (`co_case.py:753`). Thêm `bom_loaded` = thêm
   1 dòng label + chỉnh gating. Forward-compat: status lạ không crash.
5. **Gating hiện tại** (`attach_origin_sheet_states:1286-1296`, `origin_sheet_action_error:1343`,
   `origin_sheet_export_blockers:1336`): `can_lock` cần `status == "calculated"`; export chặn
   `{draft, stale, calculating}`. `bom_loaded` cần được xử như "chưa tính": chặn lock + chặn export.

## Scope

**Trong phạm vi:**
1. **Endpoint mới `POST …/origin/sheet/{code}/load-bom`** (mỏng): build context từ cache **không
   refresh tồn** (không gọi `_calculate_stock_rows_from_snapshot`; `stock_rows=[]`), gọi
   `prepare_case_origin_sheet(..., allocate=False)`, `attach_*` (bom_snapshot, bom_product_codes,
   readiness, sheet_states), `set_origin_sheet_status(bom_loaded)`. **KHÔNG** cascade-stale sheet sau
   (Load BOM không đụng pool tồn nên không làm sheet khác cũ đi). Persist.
2. **Tham số `allocate: bool = True`** xuyên `prepare_case_origin_sheet → origin_product_from_invoice_match
   → origin_material_from_bom_row`. `allocate=False`: bỏ `case_allocation_pool` + vòng
   `apply_existing_origin_product_consumption` + `allocate_material_stock`; trả material với field cấu
   trúc đầy đủ và field phân bổ **trung tính** (`allocation_lines=[]`, `material_value=""`, `vnm=""`,
   `valuation_status="not_calculated"`, `allocation_status="pending"`, **không** cảnh báo "thiếu tồn").
3. **`bom_loaded` vào status enum** = "Đã nạp BOM"; `not_calculated` vào `valuation_status_label`
   = "Chưa tính". Cập nhật gating: export_blockers += `bom_loaded`; lock vẫn cần `calculated`
   (bom_loaded tự động bị chặn); calculate cho phép từ `bom_loaded`.
4. **Frontend:** tách nút "Load BOM" (1135) thành **hai**: "Load BOM" → `/load-bom`,
   "Tính bảng kê" → `/calculate` (giữ nguyên backend allocate=True). Cập nhật nhãn pill, message JS
   (`co_case.html:1997`, 2135), tooltip. "Chốt" giữ điều kiện `origin_can_lock`.

**Ngoài phạm vi Phase 2:**
- #14 auto-load BOM mặc định khi mở hồ sơ, #13 batch load→batch tính: Phase 2 là **nền** cho chúng;
  không làm ở đây.
- Phase 3 (dọn nhiễu lịch sử tồn CO display-only) — riêng.
- Freshness `remaining_qty` snapshot (memory `origin-costock-freshness-deferred`) — vấn đề khác.

## Decisions

- **D1. Endpoint riêng `/load-bom`, không phải flag trên `/calculate`.** Frontend cần 2 nút phân biệt;
  endpoint mới mỏng, `/calculate` giữ nguyên (giảm rủi ro hồi quy đường tính).
- **D2. `allocate=False` reuse cùng builder + cùng shape dict** (thêm nhánh sớm trong
  `origin_material_from_bom_row`), KHÔNG viết builder song song. Lý do: template + `sheet_edit_bom_rows`
  + override phụ thuộc đúng shape; reuse đảm bảo không drift. Nhánh phải **chủ động** đặt allocation
  trung tính (không để pool rỗng rơi vào nhánh `shortage` → cảnh báo "thiếu tồn" sai).
- **D3. Load BOM KHÔNG cascade-stale sheet sau.** Khác `/calculate`: không đụng tồn ⇒ không làm sheet
  khác cũ. Giảm nhiễu trạng thái.
- **D4. Biên tập ở `bom_loaded`:** giữ hành vi hiện tại `edit-row`/`add-row` → `stale` (rồi "Tính bảng
  kê" xử `stale→calculated`). Không thêm đường "structure-recalc" ở v1. (Hệ quả: sửa NVL ở bom_loaded
  hiện pill nhảy sang "Cần tính lại" — chấp nhận, tinh chỉnh sau.)

## Risks

- **R1. Nhánh `allocate=False` phải đặt đủ field trung tính.** `origin_material_from_bom_row` trả ~45
  field; thiếu một field allocation → template/`enrich_origin_*` có thể KeyError hoặc tính nhầm. Đọc kỹ
  return dict (1935-1986), set tường minh từng field phân bổ về rỗng/pending.
- **R2. `enrich_origin_product`/`attach_origin_readiness` không được coi bom_loaded là "shortage/missing".**
  `enrich_origin_product:2272` đếm `valuation_status=="missing_unit_value"` và `allocation_status=="shortage"`
  để ra LVC tạm tính + cảnh báo. `not_calculated`/`pending` phải **không** lọt vào hai nhóm đó → readiness
  hiện "review/chưa tính" sạch, không cảnh báo giả.
- **R3. Template render sheet bom_loaded sạch.** Các cột allocation (trị giá, tồn khả dụng, đơn giá)
  rỗng — xác minh hiển thị gọn, không vỡ layout, không badge "Thiếu tồn CO" sai. Pill mới
  `origin-sheet-state-bom_loaded` cần CSS (rơi về style mặc định nếu thiếu — kiểm tra).
- **R4. Override clobber.** `/calculate` xoá `material_overrides` của sheet đích (1549-1551). Nếu user
  Load BOM → sửa NVL (tạo override) → bấm Tính bảng kê, override **bị xoá**? Kiểm: đó là nhánh
  `if previous.get("material_overrides")` chỉ chạy khi `target_index>=0` *sau* prepare — cần xác minh
  Tính-bảng-kê-sau-khi-sửa giữ hay bỏ chỉnh sửa. Đây là **rủi ro UX chính**, test kỹ kịch bản
  load→sửa→tính. (`save` đường khác — giữ override + recalculate.)
- **R5. `origin_can_calculate` đổi nghĩa.** Nút này giờ là "Tính bảng kê". `origin_can_load_bom` mới =
  cùng điều kiện (not locked, not sequence-blocked) hay nới hơn? Quyết định đơn giản: dùng chung gate.
- **R-test.** Test chạm: `test_co_demo.py`, `test_co_case_list_status.py`, `test_origin_narrow_source_context.py`.
  Test mới: (a) `/load-bom` ra `bom_loaded` + materials khai triển + **0** claim tồn (file-mode đủ —
  không đụng ledger); (b) bom_loaded **không** lock được; (c) load→Tính bảng kê ra `calculated` + tồn
  được phân bổ (cần `.env`/DB cho ledger thật — memory `test-env-filemode-vs-datahub`); (d) load→sửa→tính
  giữ đúng chỉnh sửa (R4).

## Quyết định user (2026-06-07)

- **DU1. GIỮ chỉnh sửa khi "Tính bảng kê"** (chọn option 1). ⇒ Sửa nhánh xoá override `/calculate`
  1549-1551: khi sheet **có** `material_overrides`, "Tính bảng kê" phải **áp** override (đường
  `recalculate_origin_sheet_edits` / `sheet_edit_bom_rows`) rồi phân bổ — KHÔNG vứt. Khi không có
  override, khai triển tươi từ BOM artifact + phân bổ (như nay). Material khai triển cấu-trúc-only ở
  `bom_loaded` đủ field cho `sheet_edit_bom_rows` (xem Phát hiện #3).
- **DU1b. Phải hỗ trợ CẢ hai chiều:** (a) Load BOM → sửa → Tính (giữ sửa); (b) **Tính xong rồi mới
  thay NVL** — đường `edit-row`/`save`/`recalculate_origin_sheet_edits` hiện có giữ nguyên, vẫn áp
  override khi tính lại. Nghĩa là "áp override khi tính lại" là hành vi chung cho mọi lần tính-có-override.
- **DU2. Nhánh:** tạo branch mới **từ `co-stock-detangle-phase1`** (Phase 1 chưa merge, cùng đụng
  `/calculate`); gộp deploy chung.

## Open Questions (còn lại, minor — tự quyết khi code)

1. **Nhãn `bom_loaded`** — đề xuất "Đã nạp BOM" (pill ngắn). Tự chốt khi code.
2. **Load BOM khi đang `calculated`/`stale`/`bom_loaded`:** cho từ mọi status ≠ locked (giống
   calculate); nạp lại = về `bom_loaded`. Nạp-lại-tường-minh **xoá** override (reset về artifact); chỉ
   "Tính bảng kê" mới giữ override (DU1).

## Next step

**`/tdd`** trên branch mới từ `co-stock-detangle-phase1`: (1) test `/load-bom` ra `bom_loaded` +
materials khai triển + 0 claim tồn (file-mode); (2) thêm `allocate=False` path; (3) sửa `/calculate`
áp override thay vì xoá (DU1); (4) test load→sửa→Tính giữ chỉnh sửa; (5) tách nút frontend + nhãn.
Rồi `/rev`.
