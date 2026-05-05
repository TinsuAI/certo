# Feature: Sequential Product Allocation For Origin Sheets

## Scope

One shipment can contain multiple finished products. Each finished product has its own origin sheet / bảng kê, but the C/O stock calculation for those sheets must run in a single ordered sequence.

This feature makes the sequence explicit:

- Product sheets are calculated one after another in the shipment product order.
- Each material allocation mutates the case snapshot stock pool before the next material or product is calculated.
- Later product sheets see only the remaining C/O stock after earlier product sheets have consumed it.
- The UI shows the product sequence and allocation effect so operators understand why product B may have shortages after product A is calculated.

This does not implement a global reservation ledger across dossiers. The current behavior remains snapshot-only inside one C/O case unless a Data Hub-owned stock ledger is approved separately.

## Decisions

- Treat product order as a first-class snapshot input.
  - Default order should follow export invoice / BCCT export row order.
  - The snapshot should persist the order used for calculation.
  - Reordering products must require recalculation because every later sheet can change.
- Operators can reorder products in the origin UI for the next recalculation.
  - The currently displayed sheets remain the last calculated snapshot.
  - The reordered sequence is written to `origin_product_order`.
  - `Tính lại snapshot` rebuilds product sheets in that order and then updates the visible allocation sequence.
- Keep one visible sheet per finished product, but display the workbook as a sequence, not independent tabs.
  - Sheet tabs should show labels like `1`, `2`, `3` or `Bước 1`, `Bước 2`.
  - Each sheet should show `Tồn đầu bước`, `Đã dùng ở bước này`, and `Tồn sau bước` at least in allocation detail.
  - Later sheets with shortages should link the shortage back to earlier product/material allocations that consumed the same stock lines.
- Preserve deterministic automatic allocation.
  - Use the existing case-level `co_stock_allocation_pool(stock_rows)`.
  - Iterate products in product order.
  - Inside each product, iterate BOM material rows in their BOM order.
  - Inside each material, consume stock candidates by the existing stock allocation sort key.
- Add audit fields to the snapshot/export.
  - Product allocation sequence number.
  - Material allocation sequence number within product.
  - Stock line opening quantity before allocation.
  - Allocated quantity.
  - Stock line remaining quantity after allocation.
  - Optional `consumed_by_product_code` / `consumed_by_material_code` trace for explaining shortages.

## Risks

- If product order is hidden, operators may assume sheets are independent and dispute shortage results.
- Changing BOM version or product order invalidates all later product sheets, not just the edited sheet.
- The current UI uses tab metaphors, which can imply parallel sheets. The visual design must make the order obvious.
- If the same stock row is reachable through multiple keys, allocation must keep using shared row objects so one consumption is reflected everywhere in the pool.
- Global stock reservation across dossiers is a separate problem and should not be implied by this UI.

## Open Questions

- Should operators be allowed to manually reorder products, or should order be locked to invoice / BCCT row order?
- If reordering is allowed, should the UI show a before/after diff for shortages and LVC results before saving?
- When a later product is short, how much cross-reference is enough: product code only, or exact earlier material + declaration line allocations?
- Should export workbooks include one combined allocation ledger sheet in addition to per-product origin sheets?

## Recommended Next Step

Implement a small UI and snapshot enhancement first:

1. Add sequence labels and a short `Tính tuần tự theo tồn CO` strip above sheet tabs.
2. Add product-level hidden fields for `allocation_sequence`.
3. Add allocation-line fields for opening and remaining quantities around each allocation.
4. Add tests proving product A can consume stock and force product B into shortage when both products use the same material.
