# Project Status

## Current State
- Active branch: `main`; do not push unless the user asks.
- Local CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returned `{"status":"ok"}` on 2026-05-05.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- The C/O origin page now supports snapshot-only, case-level sequential allocation across multiple finished products:
  - one shipment can have multiple TP / bảng kê
  - TP are calculated one by one against the same mutable C/O stock pool
  - later TP see stock after earlier TP have consumed it
  - each product/material/allocation line carries sequence metadata for audit
  - allocation lines record opening quantity, allocated quantity, and remaining quantity
  - shortages can show that stock was already used by an earlier TP
- Operators can change the product calculation order in the origin UI:
  - the `Thứ tự tính lại` control has `Lên` / `Xuống` buttons
  - the UI writes `origin_product_order`
  - `Tính lại snapshot` rebuilds products in that order
  - displayed sheets remain the last calculated snapshot until recalculated
- XLSX export includes the new sequence and opening-quantity trace in `Origin Snapshot` and `LVC Statement`.
- The origin material table still supports compact parent rows, expandable dòng tồn rows, warning filters, and optional column visibility.
- Pre-existing unrelated worktree artifacts remain separate and should not be committed unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
- Local screenshot artifacts remain under `.ai/screenshots/co-case-origin-ux/`; they are not required for the current commit.

## Recent Changes
- Added `.ai/features/2026-05-05-origin-sequential-product-allocation.md` to capture the sequential allocation design.
- Implemented product order override for origin calculations:
  - `origin_product_order` is parsed from form data, persisted in case records, and used to sort invoice matches before allocation.
  - `origin_snapshot.product_order` records the product order used for the snapshot.
- Added allocation trace fields:
  - `allocation_sequence` on products
  - `material_sequence` on materials
  - `product_sequence`, `product_code`, `material_sequence`, and `opening_qty` on allocation lines
  - `allocation_shortage_trace` for explaining shortages caused by earlier products
- Updated origin UI:
  - sheet tabs show `Bước n`
  - a sequence note explains non-parallel stock consumption
  - a reorder control lets operators change the order for the next recalculation
  - allocation detail rows show opening and remaining stock quantities
- Updated workbook export and tests for the new trace fields.
- Verification completed:
  - `uv run pytest` passed: `171 passed in 32.34s`
  - `curl -fsS http://127.0.0.1:8001/healthz` returned `{"status":"ok"}`

## Next Steps
1. Manually review the origin UI reorder control in a browser on a real multi-TP case.
2. Decide whether product reorder should be drag-and-drop later; current implementation intentionally uses explicit `Lên` / `Xuống` controls.
3. Decide whether global stock reservation across dossiers is required. If yes, design/approve a ledger, likely Data Hub-owned, before decrementing shared stock globally.
4. Revisit mixed-currency allocation rules before automatically summing VNM across currencies.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: briefly say what was inspected, what failed, and how it was resolved.
- Current allocation behavior is snapshot-only inside CO. It consumes a mutable in-memory pool while building a case snapshot, but it does not reserve or decrement shared stock across dossiers.
- Product order is now a business input for the snapshot. If the user changes order, always recalculate before interpreting shortages.
- The term to use in Vietnamese UI is “dòng tồn”, not “lot”.
- Warning summary filtering is intentionally per product sheet and single-select for now.
- Column visibility is stored in browser `localStorage` key `barryCo.origin.hiddenColumns`.
- Do not commit the unrelated `docs/co-form-index-confirmation.*` changes unless the user explicitly asks.
