# Feature: Standalone CO-stock snapshot import (remaining-based) từ trừ-lùi

Discovery brief (gọn). Chốt hướng 2026-06-14 sau khi review Trục A. Thay cho Trục A
(làm hướng này thì Trục A vô nghĩa). Nối [[co-stock-workbook-converter]],
brief `2026-06-14-co-stock-key-bom-matching-unification.md`.

## Ý tưởng (user)
Workbook trừ-lùi đã có sẵn cột **"Tồn" (remaining)** mỗi lô (verified = opening − Đã_xuất,
4000/4000 cả Growatt + Johnson). → Converter xuất thẳng `remaining`; import **set thẳng remaining**
vào co_stock theo `(decl, line)`. KHÔNG fold, KHÔNG khớp BCCT theo customs_code → bỏ luôn
`matching_code` + Trục A. Workbook = chân lý (đúng cho client chạy Excel song song).

## Scope (IN)
1. **Template chuẩn**: thêm cột `remaining_qty` (optional; reader bỏ qua nếu thiếu → fallback opening−used).
2. **Converter** (`co_stock_workbook.py`): xuất `remaining` = `opening − used`, **cross-check cột "Tồn"**
   của workbook, lệch thì cảnh báo (bắt lô sửa tay/cache cũ). Vẫn giữ opening + used (để hiển thị Tồn/Đã dùng/Còn lại).
3. **Standalone import** (đường mới): standard template → set `co_stock_rows` TRỰC TIẾP cho client:
   - lot identity = `(declaration_no, line_no)`; remaining **bake thẳng**; opening/used giữ làm thuộc tính.
   - `allocation_code` = `resolve_allocation_code(name, config)` (description_regex cho Growatt) → BOM khớp.
   - eligibility active; KHÔNG fold; full-mode **replace** (re-import ghi đè; lô đang bị claim giữ lại).
   - mark `co_stock_source="workbook_snapshot"`.
4. **Guard**: client workbook-sourced KHÔNG bị "Refresh từ Data Hub" đè (skip/preserve).
5. **Web**: nút "Nạp snapshot vào tồn CO" ở panel converter (đường import standalone).

## Scope (OUT)
- KHÔNG đụng đường overlay cũ `/co-stock/import` (giữ cho client dùng tồn-DH).
- KHÔNG Trục A (moot). KHÔNG gỡ fold lõi DH (CS2 riêng).

## Decisions (giả định — user sửa nếu sai)
- remaining lấy `opening − used`, cross-check "Tồn"; lệch → warn, vẫn dùng opening−used (đã verify khớp).
- Standalone dùng materializer seam với `fold=False` (đường tôi từng thêm rồi gỡ — khôi phục lại).
- Re-import = reset baseline; ledger in-app overlay ở read (`remaining − claim`), coi là practice.
- Client standalone tách khỏi tồn DH (workbook = truth).

## Risks
- **SAI TỒN** nếu set remaining sai → remaining = "Tồn" đã verify (=K−Q 4000/4000) + parity test.
- **DH refresh đè snapshot** → guard skip workbook-sourced client (R quan trọng nhất).
- **Re-import vs ledger in-app** double-count (export vừa ở "used" workbook vừa ở claim) → reset baseline khi re-import.
- Over-claim guard đọc `remaining_qty` column → set thẳng nên vẫn đúng.
- Client lẫn lộn (vừa adjustments cũ vừa snapshot) → standalone ghi đè co_stock_rows; cân nhắc clear adjustments client đó.

## Blast radius (nhỏ hơn Trục A nhiều — additive, KHÔNG schema migration, KHÔNG đụng key/fold lõi)
- `co_stock_template.py` (+ cột remaining_qty), `co_stock_workbook.py` (converter remaining + cross-check;
  `stock_rows_from_standard` bake remaining + allocation via config), `routers/co_stock.py` (endpoint
  standalone), `co_stock_materializer.py` (re-add `fold=False` param), refresh guard, `co_case.html` (nút).

## Parity-test plan (/tdd)
- file-mode: converter remaining == Tồn == opening−used; cross-check warn khi lệch; stock_rows_from_standard
  có remaining baked + allocation_code resolved (description_regex) + eligibility active + opening/used giữ.
- apply_used_qty overlay: `remaining − ledger` đúng (empty ledger = remaining; có claim = trừ thêm; overclaim flag).
- DB: standalone import set co_stock_rows; re-import replace; remaining == workbook Tồn; BOM pool match cao.

## Status — IMPLEMENTED (TDD, 2026-06-14)
Done test-first: template `remaining_qty` col; converter bakes remaining + cross-checks "Tồn"
(`summary.ton_mismatch`); `stock_rows_from_standard(rows, config)` (remaining baked, allocation via
`resolve_allocation_code`, eligibility active); `apply_used_qty` honours baked remaining
(`baseline_used = opening − remaining`); standalone `import_standard_snapshot` (materializer
`fold=False`, full replace); `/co-stock/import-snapshot` route; `is_workbook_sourced` DH-refresh guard;
UI panel "Nạp tồn CO từ workbook trừ-lùi (snapshot)". Tests: file-mode **596 pass** + DB co_stock subset
**53 pass** + e2e `e2e_costock_workbook_snapshot.cjs` **12/12**. **Chưa commit.** Next: `/rev` → commit.
