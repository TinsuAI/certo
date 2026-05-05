# Session: Origin Sequential Product Allocation

Date: 2026-05-05

## What Was Done

- Clarified the business rule: one shipment can include multiple finished products, producing multiple origin sheets / bảng kê, but C/O stock calculation must be sequential rather than parallel.
- Added a feature brief at `.ai/features/2026-05-05-origin-sequential-product-allocation.md`.
- Implemented case-level sequential allocation trace:
  - products receive `allocation_sequence`
  - materials receive `material_sequence`
  - allocation lines receive `product_sequence`, `product_code`, `material_sequence`, and `opening_qty`
  - shortages can carry `allocation_shortage_trace` explaining earlier product consumption
- Added product order override:
  - `origin_product_order` is parsed from form data
  - case records persist and restore it
  - origin snapshot stores `product_order`
  - `prepare_case_origin_products()` sorts invoice matches by this order before rebuilding the stock allocation snapshot
- Updated the origin UI:
  - sheet tabs now read as `Bước n`
  - a note explains that C/O stock is consumed sequentially
  - `Thứ tự tính lại` controls let operators move TP up/down
  - a dirty message tells operators to click `Tính lại snapshot` after changing order
  - allocation detail rows show opening and remaining quantities
- Updated XLSX export:
  - `Origin Snapshot` includes sequence information
  - `LVC Statement` includes product/material sequence and allocation opening quantity
- Added regression tests:
  - product A consumes stock and makes product B short
  - reversing order makes product B consume stock first and product A short
  - web form/export round-trip includes the sequence/order fields

## Decisions Made

- Default product order follows export invoice / BCCT row order.
- Product order is treated as a snapshot input, not a visual-only tab order.
- Reordering in the UI changes the next calculation order; it does not mutate the already displayed calculated rows until the user clicks `Tính lại snapshot`.
- Use explicit `Lên` / `Xuống` buttons instead of drag-and-drop for now, because the workflow needs clarity and keyboard-friendly controls more than a richer interaction.
- Keep allocation snapshot-only inside CO. Global reservation across dossiers remains a separate ledger/Data Hub contract decision.

## What Didn't Work

- A first hidden-field pass placed `data-origin-product-order` before `value`, so the existing test helper did not capture `origin_product_order`; the input was reordered to keep `type`, `name`, and `value` first.
- Shortage trace initially included all prior consumptions on the stock row, including the current product's partial allocation. It was narrowed to only earlier product sequences so `Đã dùng ở bước trước` is accurate.
- An exploratory sub-agent was started for code reading but did not return before the design was already confirmed from local code; it was closed without using its result.

## Open Items

- Manually review the reorder UI on a real multi-TP case in the browser.
- Decide whether reorder should become drag-and-drop later.
- Decide whether the export should add a dedicated combined allocation ledger sheet in addition to the current `Origin Snapshot` and `LVC Statement` trace columns.
- Decide whether global stock reservation across dossiers is needed before implementing any cross-dossier decrement behavior.
- Revisit mixed-currency allocation behavior before automatically summing VNM across currencies.
