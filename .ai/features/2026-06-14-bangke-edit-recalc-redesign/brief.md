# Feature: Bảng kê C/O — sửa data-loss khi xoá NVL (BG1) + làm logic luồng edit ⇄ Tính ⇄ Load BOM

Discovery brief. Gom **BG1** (`.ai/BACKLOG.md` › Bug — Bảng kê) với phần redesign luồng edit/recalc
mà user nêu trong phiên 2026-06-14. Đã review code 3 vùng (client JS, server save+recalc+fold, Load
BOM/Tính). Quyết định đã chốt với user qua hỏi-đáp (xem Decisions). Tiếp theo: `/tdd` toàn bộ.

## Bối cảnh — hai nửa code đá nhau vì override key theo VỊ TRÍ

Override chỉnh-sửa-sheet (xoá / thêm / sửa ĐM / thay thế) được key bằng **vị trí dòng** `loop.index0`,
không phải ID bền:
- Template emit `data-row-index="{{ loop.index0 }}"` (`co_case.html:1421,1503,1529`); client stage
  `ops.deletes[rowIndex]=true` (`:4759`); save ghi `overrides[str(row_index)]={"deleted":True}`
  (`co_case.py:2473`), **merge tích luỹ** từ `previous` (`:2416`).
- **Template được thiết kế theo giả định: dòng deleted VẪN nằm trong `product.materials`**, chỉ bị fold
  bằng cờ `norm_override.deleted` tra theo index (`co_case.html:1427-1432`) → index phải ổn định.
- **Nhưng `recalculate_origin_sheet_edits` (chạy sau MỖI save) lại co `materials`:** `sheet_edit_bom_rows`
  `continue` bỏ hẳn dòng deleted (`co_case.py:594`), `origin_product_from_invoice_match` dựng lại
  `materials` từ danh sách đã co (`co_case_context.py:1748-1761,1807`), rồi **persist list đã co + GIỮ
  nguyên override key theo index cũ, không remap** (`co_case.py:585-587`).
- `attach_origin_sheet_states` chỉ gắn metadata, **không** dựng lại materials (`co_case_context.py:1165-1261`)
  → list đã co được giữ luôn ở các lần render/save sau.

## Triệu chứng BG1 (data-loss thật — đã trace bằng code)

Xoá 1 dòng → mất 2, fold "đã xoá" kẹt ở 1, tổng không bảo toàn:
1. Xoá dòng `i` → save → materials co còn N−1, **nhưng** override `{"i":deleted}` vẫn còn.
2. Render N−1 dòng: key `i` rơi trúng **dòng kế bên (đã dịch lên)** → dòng đó bị fold "đã xoá" **oan**
   → user thấy còn N−2. `diff_removed` đếm số key deleted = **1** (`co_case_context.py:1241`) → fold báo "1".
3. Xoá tiếp: recalc enumerate N−1, bỏ index `i` (= **dòng oan, mất thật**) + index mới → **mất 2 dòng/lần**,
   count vẫn kẹt ~1 (key index thấp bị tái dùng/đè). → **bảng kê thiếu NVL ⇒ sai LVC/VNM + sai BOM khi Chốt.**
4. "Lúc hiện fold lúc không": summary ẩn khi không key nào trúng dòng còn sống → bấp bênh theo độ dịch index.

## Phát hiện liên quan (đã review code)

- **Edit đã auto-calc:** `/save` gọi `recalculate_origin_sheet_edits` với `allocate=True`
  (`co_case.py:2521`) → phân bổ tồn + VNM/LVC đầy đủ, set `calculated` (`:2510-2525`) + đánh stale các
  sheet sau (`mark_origin_sheets_stale(target+1)`, `:2526`). ⇒ "Tính bảng kê" bấm ngay sau khi sửa = no-op.
- **"Tính bảng kê" là leftover thiết kế 2-bước cũ:** docstring `co_case.py:2391` còn nói "flipped to
  stale, next /calculate applies" (sai — code set `calculated`). `origin_can_calculate = status!='locked'
  and not sequence_reason` (`co_case_context.py:1289`) → nút **luôn bật** kể cả đã tính.
- **Vẫn còn 2 vai trò thật của "Tính bảng kê":** (a) tính sheet vừa Load BOM mà **không sửa** (Load BOM =
  `allocate=False`, chỉ cấu trúc, chưa tồn/LVC — `co_case_context.py:1772-1776`); (b) **tính lại sheet
  `stale`** downstream — vì **tồn CO là pool dùng chung giữa các sheet**, phân bổ sheet sau đổi khi sheet
  trước ăn tồn khác đi; thao tác này phải do operator chủ động (thứ tự ăn tồn chung là quyết định nghiệp vụ).
- **Load BOM xoá sạch chỉnh sửa, không cảnh báo:** `co_case.py:1582-1587` reset `material_overrides={}`;
  không confirm, chỉ tooltip (`co_case.html:1121`) — mà tooltip nói sai "chưa lưu" trong khi vứt cả cái đã lưu.
- **Hai đường xoá không nhất quán:** bulk (`stageRowDeletion`/`wireSheetBulkDelete`) có `confirm()`
  (`co_case.html:4814`); modal thay thế "Xoá dòng này" (`removeRow:4036→4041`) **không confirm**.

## Decisions (đã chốt với user)

1. **Xoá NVL = soft delete.** Giữ dòng, fold + gạch mờ, bỏ chọn để khôi phục. (Trùng với cách sửa data-loss.)
2. **Sửa data-loss = ngừng co `materials`.** Giữ dòng deleted trong materials (gắn cờ) → index ổn định
   vĩnh viễn → template fold sẵn có chạy đúng; phần tính (phân bổ / VNM / LVC) **loại trừ** dòng deleted
   (đóng góp 0). `diff_removed` đếm tích luỹ chính xác. Cân nhắc key override theo **ID bền**
   (`source_row` / `material_sequence`, đã có hidden input `co_case.html:1444-1448`) để xử lý luôn ca xoá
   dòng "thêm mới" (`added_*`) — quyết khi implement nếu phạm vi cho phép.
3. **Gộp 2 đường xoá** về một sink + hành vi nhất quán (cả bulk lẫn "Xoá dòng này").
4. **Modal cảnh báo xoá: chỉ khi xoá hàng loạt** (select-all / nhiều dòng / "Lọc dòng lỗi"); xoá 1 dòng lẻ
   xoá ngay (có Ctrl+Z khôi phục + soft-delete cho phép bỏ chọn).
5. **"Tính bảng kê" contextual (giữ 2 bước).** Bật khi `draft/bom_loaded/stale`; khi `calculated` & không
   stale → disable + title "Đã tính — sửa bảng kê sẽ tự tính lại"; nhãn động **"Tính bảng kê" / "Tính lại"**.
6. **Load BOM:** modal cảnh báo "sẽ ghi đè bảng kê hiện tại" khi sheet đang có dữ liệu/chỉnh sửa.
7. **KHÔNG** auto-recalc stale downstream / **KHÔNG** auto-calc trên Load BOM (giữ kiểm soát phân bổ tồn chung).

## Cách sửa (server, P0)

- `sheet_edit_bom_rows` (`co_case.py:589`): **không `continue`** trên deleted — phát ra row có cờ
  `deleted`/`row_class="deleted"` để materials giữ đủ độ dài + thứ tự (index ổn định).
- `origin_product_from_invoice_match` / `origin_material_from_bom_row` (`co_case_context.py:1728/1918`):
  dòng `deleted` → **không phân bổ tồn, non_origin_cif_value=0, loại khỏi tổng VNM + khỏi cờ
  missing_material_values/LVC**. Hiển thị trong materials (foldable) nhưng đóng góp 0.
- Template: fold theo cờ trên dòng (`material.deleted`) thay vì chỉ tra override theo index — bền hơn.
- Kết quả bất biến cần test: xoá k dòng (k=1..) → `len(materials)` GIỮ NGUYÊN, số dòng active = N−k,
  `origin_sheet_material_diff_removed == k`, các dòng còn lại + ĐM + phân bổ **không đổi danh tính**.

## Risks

- `materials` phục vụ **đôi nhiệm** (hiển thị + tính). Giữ deleted-in-materials phải chắc mọi điểm tính
  (VNM sum, LVC, allocation pool consume, shortage flags, **export bảng kê HQ** `workbook_io.py`, **propose-BOM**
  `build_bom_proposal_rows:2247` cũng index-keyed `deleted` skip) đều loại đúng dòng deleted. Đặc biệt
  `build_bom_proposal_rows` hiện cũng bỏ deleted theo index — phải đồng bộ logic mới.
- **Dữ liệu cũ đã hỏng (prod/dev):** sheet đã từng xoá theo code cũ có materials đã co + override index
  lệch. Sửa code không tự lành dữ liệu cũ. Cần: (a) test trên case sạch; (b) cân nhắc 1 lần re-Load BOM
  để dựng lại materials đầy đủ, hoặc migration nhẹ. Repro gốc: `growatt-vn/co-case-e44fe2065b62`.
- **Sheet đã-tính-từ-trước thiếu `customs_relevance`** ([[technical-flattened-export-noise]], DC3) — không
  trực tiếp BG1 nhưng cùng vùng recalc; đừng làm hồi quy.
- **Wiring sống qua shell-swap:** mọi control xoá/Tính/Load-BOM mới phải document-delegated hoặc trong
  `refreshCaseShellInteractions` (memory [[origin-wiring-must-survive-shell-swap]]) nếu không chết sau Tính/Chốt.
- `recalculate_origin_sheet_edits` trả early khi `not overrides` (`co_case.py:520`) — soft-delete tạo override
  nên vẫn chạy; nhưng kiểm ca all-deleted (materials rỗng active) không vỡ LVC (`missing_bom_materials`).
- Đụng `origin_case_revision` (memory [[bom-load-race-no-inflight-guard]]): cờ deleted trên row là derived,
  **không** được lọt vào revision token (chỉ user-state).

## Test plan (TDD — pure server first)

P0 (unit, không cần `.env`, file-mode [[test-env-filemode-vs-datahub]]):
1. `sheet_edit_bom_rows`: overrides có `{"i":deleted}` → output GIỮ đủ độ dài, dòng `i` có cờ deleted,
   các dòng khác giữ nguyên material_code/thứ tự.
2. `recalculate_origin_sheet_edits`: fixture N dòng → xoá 1 (override `{i:deleted}`) → `len(materials)==N`,
   active==N−1, `origin_sheet_material_diff_removed==1`; xoá thêm 1 (override `{i:deleted, j:deleted}`) →
   active==N−2, `diff_removed==2`, KHÔNG mất dòng nào ngoài i,j (so danh tính material_code).
3. VNM/LVC: dòng deleted đóng góp 0; tổng VNM = tổng dòng active; không bịa LVC khi all-deleted.
4. `build_bom_proposal_rows`: loại đúng dòng deleted theo logic mới (không lệch index).
5. Regression: thay thế + sửa ĐM trên dòng KHÔNG bị dịch khi có dòng deleted phía trên (off-by-one cũ).

P2/P5: `co_case_origin_sheet_save` round-trip (DB test cần `.env`) — xoá → reload → state đúng.

UI (P1–P3): Playwright e2e + screenshot + **đánh giá ảnh** [[dev-flow-e2e-screenshot-eval]]; tái dùng
`.ai/scripts/e2e_bangke_split.cjs`. Kịch bản: xoá lẻ (fold, count++), xoá hàng loạt (modal cảnh báo),
Load BOM khi có edit (modal ghi đè), nút Tính disable khi đã calculated / "Tính lại" khi stale.

## Sequencing (1 branch `feat/rd3-bangke-split`)

- **P0** — Fix data-loss server (Decisions 2). TDD trước. Ưu tiên cao nhất (data-integrity).
- **P1** — Gộp 2 đường xoá + modal cảnh báo bulk (Decisions 3,4).
- **P2** — "Tính bảng kê" contextual + nhãn động (Decisions 5).
- **P3** — Load BOM overwrite modal (Decisions 6).
- **Verify** — e2e + screenshot eval; `/rev`; rồi commit theo từng P.

## Open Questions

1. Dữ liệu cũ đã hỏng: chỉ fix-forward (re-Load BOM thủ công) hay viết migration dựng lại materials? (đề
   xuất: fix-forward + note, vì re-Load BOM đằng nào cũng dựng lại đủ).
2. Soft-delete: có cho "xoá vĩnh viễn" (ẩn hẳn khỏi fold) sau khi chốt không, hay luôn giữ foldable? (đề
   xuất: luôn foldable; chốt rồi thì khoá toàn sheet).
3. Modal cảnh báo bulk có liệt kê tên NVL sắp xoá hay chỉ đếm số dòng? (đề xuất: đếm + 3-5 tên đầu).
