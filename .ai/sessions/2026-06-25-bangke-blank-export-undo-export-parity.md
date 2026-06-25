# Session 2026-06-25 — Bảng kê: blank export root-cause, undo/redo, export==web parity

## Context (client feedback)
1. "Xuất bảng kê nó **vẫn bị trống**" (Johnson) — ảnh: nhiều dòng trống HẾT (mã/tên/HS/trị giá/tờ
   khai), chỉ còn đơn vị + lượng.
2. Autosave quá nhanh ("sai chưa kịp sửa đã lưu mất") → muốn nới + configurable; audit undo/redo; undelete.

## Investigation arc (overturns the 2026-06-20 DC2 theory)
- Bắt đầu nghĩ "thiếu tên" → tưởng là DC2 (DH `bom_observed` payload={} thiếu tên, 3 artifact
  `.ai/api-requests/2026-06-20-bom-*`). **SAI.** Probe in-container trên prod johnson `co-case-0831c090c648`:
  DH có **đủ tên cho 100% mã** (13.594 materials). Root cause là **phía CO**.
- Đường **fast `/calculate`** (snapshot path, `co_case.py:1996`) truyền `material_rows=[]` (context nhẹ)
  vào builder. `customs_relevance` cũng copy từ catalog (`co_case_context.py:2064,2287`) → catalog rỗng
  → **`customs_relevance=0` cho MỌI material** → `is_bom_technical_noise` không loại được gì → rác
  (`excluded_non_material`) + chưa-khớp (`declarable_unmatched`) **lọt vào export thành dòng trống**;
  thêm tên rỗng cho dòng không khớp tồn. Bằng chứng: catalog rỗng → 1019/1909 trống; catalog đủ → 0.
- "Dòng đã xoá vẫn ra export": xác minh **xoá tay được tôn trọng đúng** (per-sheet theo index); 5 "leak"
  là cùng NVL còn dùng ở SP khác (cross-sheet, hợp lệ).

## Decisions + fixes (committed 763fe74)
- **#1A catalog ở bước Tính**: `_material_catalog_rows` (catalog-only, no 65k BCCT, TTL 90s) +
  `_ensure_origin_material_rows` ở 4 chỗ build (calculate / load-bom / preview / recalc-edits). Tách
  `_recompute_origin_sheet_context` dùng chung cho /calculate + undo/redo.
- **#1B fallback tên/HS từ CO Stock/BCCT** theo mã (`origin_material_from_bom_row`); pool giữ MỌI lô.
- **Export == web (HARD RULE user chốt):** export là **render thuần, KHÔNG logic riêng**. (a) GỠ
  enrichment export-time tôi từng thêm (sai — vi phạm nguyên tắc); (b) `customs_relevance` **round-trip
  qua form** (`co_case.html` hidden input + `demo_data.py` parse) → đường form-rebuild faithful; (c) web
  **fold `declarable_unmatched`** như rác, nhãn "không xuất". → tập web ẩn == tập export bỏ.
- **#2 undo/redo server-side**: `override_history`/`override_redo` per-sheet (carried qua
  `attach_origin_sheet_states`, bounded 25) + route `/undo`,`/redo`; nút client bật từ history (sửa bug
  nút render mặc định `disabled` → gọi `updateSheetHistoryButtons` mỗi panel). Autosave 2s→30s
  configurable (`localStorage.coAutoSaveDelayMs` / `window.CO_AUTOSAVE_DELAY_MS` / `coSetAutoSaveDelay`).

## What didn't work / corrected
- **Export-time enrichment (`_enrich_materials_from_catalog`)**: tôi thêm để dọn sheet cũ
  (customs_relevance=0) ngay lúc export → **user bác đúng**: export khác web = nguy hiểm. ĐÃ GỠ. Cách
  đúng: logic ở Tính; sheet cũ Tính lại; form round-trip để export render đúng output của Tính.

## Verification
- Full suite **706 pass, 10 skip**.
- Browser e2e (demo-furniture, auth-off :8001): #1 names cả 2 sheet (0 trống); #2 xoá→Lưu→Undo (khôi
  phục)→Redo PASS; nút undo bật sau lưu.
- File export thật (in-process `create_hq_bang_ke_workbook`): johnson `co-case-fcc68e4a073a` 103 dòng
  trống → 0 sau khi có customs_relevance; demo-furniture 13/13 tên có trong xlsx.
- **Screenshot Johnson thật** (copy case prod→local barry_co, local DH có johnson + phân loại): 39/104
  dòng fold (33 chưa-khớp + 6 phi-vật-tư), nhãn "⚠ chưa khớp · không xuất" + summary "N dòng KHÔNG xuất
  ra bảng kê". Ảnh ở `.ai/screenshots/2026-06-25-bangke-blank-undo-export-parity/` (gitignored).

## Open items
- **P2 perf** (BACKLOG): fast `/calculate` giờ pull thêm catalog (~13k, cache) để có tên+relevance →
  re-Tín nhích chậm vài giây. Tối ưu: materialize customs_relevance+tên vào snapshot tồn.
- Sheet **đã CHỐT trước fix** (customs_relevance=0): export vẫn theo materials cũ → cần mở chốt + Tính
  lại để dọn (đúng nguyên tắc logic-ở-Tính; KHÔNG vá ở export).
- `.ai/api-requests/2026-06-20-bom-observed-material-names.md` (DC2 tên) **đã bị bác** cho vấn đề tên —
  giữ lại để tham khảo lịch sử; phần `customs_relevance` coverage (DC1) vẫn có thể còn giá trị riêng.
- Local barry_co còn 1 case johnson copy từ prod (`co-case-0831c090c648`) + vài case demo-furniture
  scratch — chỉ để test, có thể xoá.

## Memory
`bangke-blank-names-fast-path-empty-catalog`, `bangke-post-save-undo-override-history`,
`bangke-export-equals-web-invariant`.
