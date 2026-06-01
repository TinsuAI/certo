# Feature: Origin Sheet Live Allocation

## Scope

Make every material edit in the origin workbook recalculate the visible allocation child rows immediately, before save:

- Replace NVL: parent row, source summary, allocation child rows, consumed qty, unit value, material value, non-origin value, and LVC update from the replacement material's lots.
- Change ĐM: same material code, new required qty, allocation child rows reallocated from available lots, values/totals update.
- Add new NVL row: parent row and allocation child rows are created together from selected material lots and ĐM.
- Delete NVL row: parent row and allocation child rows are removed/marked deleted from live totals and pending save.
- Undo/redo must restore parent rows, child rows, pending ops, and live totals together.
- Save remains the source of truth: backend recomputes the sheet and reloads from persisted state.

Explicitly out of scope for this change:

- Legal PSR/CTC engine.
- Committing live edits to Data Hub BOM artifacts before sheet lock/propose.
- Cross-case stock ledger writes before sheet lock.

## Decisions

- Use one client-side allocation path for replace, add, and ĐM edit. Do not maintain separate parent-only formulas and child-row logic.
- Treat live allocation as a preview, not the final source of truth. The backend recompute on `Save bảng kê` remains authoritative.
- Use the same lot order and value rules as the backend as closely as possible:
  - allocate from available lots in sorted stock order;
  - decrement remaining qty by each row's allocation;
  - compute material value from allocated qty x unit value;
  - show shortage when lots cannot cover the required qty.
- Recompute at the sheet level when an edit changes stock consumption, not only the edited row. This is required because two rows in one sheet can consume the same NVL code, and changing the first row affects "tồn còn" for the second row.
- Later sheets should be marked stale after save; live browser allocation only needs to be exact for the currently edited sheet.
- The frontend should not trust stale child rows. Any row-level material operation must rebuild or remove all child rows for affected allocation groups.

## Cases

1. Replace NVL A -> B, same ĐM:
   - remove A child rows;
   - allocate B lots;
   - rebuild B child rows;
   - update parent source chip to B lot summary.

2. Replace NVL A -> B, changed ĐM:
   - same as replace, but required qty = new ĐM x product qty.

3. Change ĐM on existing row:
   - allocate the same material code again with required qty = new ĐM x product qty;
   - rebuild child rows;
   - update shortage/value/status on the parent.

4. Add new row:
   - allocate selected material from lots using entered ĐM;
   - insert parent row and child rows together;
   - include pending add op.

5. Delete existing row:
   - mark/remove parent and all child rows from live allocation;
   - pending delete op;
   - rerun later rows in the same sheet because freed stock may change their allocation.

6. Undo/redo:
   - restore full table body snapshot and pending ops;
   - recompute totals after restore.

7. Shortage:
   - show allocated child rows for partial coverage;
   - show shortage chip/parent warning;
   - keep save enabled only if business rule allows partial allocation; backend will final-check.

8. Missing unit value:
   - child row still appears;
   - parent value shows missing/partial valuation;
   - LVC is provisional.

9. Mixed currency:
   - show child rows;
   - parent value follows backend rule: block or mark mixed allocation instead of summing incompatible currencies.

## Proposed Implementation

1. Introduce a small frontend allocator module inside `co_case.html`:
   - `materialCodeForRow(row)`
   - `requiredQtyForRow(row)`
   - `stockLotsForCode(code)`
   - `allocateLots(code, requiredQty, sheetConsumptionContext)`
   - `renderAllocationRows(parentRow, allocationResult)`
   - `applyAllocationToParent(parentRow, allocationResult)`
   - `reallocateSheet(panel, changedRow)`

2. Maintain a per-sheet stock cache:
   - use candidate lots already loaded by substitute modal for replace/add;
   - for ĐM-only edit, lazily fetch `/substitute-stock?codes=<current material code>`;
   - cache by material code for the sheet.

3. On every material edit:
   - push history snapshot;
   - update pending ops;
   - call `reallocateSheet(panel, changedRow)`;
   - mark sheet dirty.

4. Reallocate from top to bottom within the current sheet:
   - this keeps repeated material codes correct;
   - deleted rows consume nothing;
   - added/replaced rows consume their effective material code;
   - existing rows consume their displayed material code.

5. Save payload stays unchanged except it carries workbook snapshot. Backend recompute remains final and reloads the page.

## Risks

- Frontend allocator can drift from backend allocator if duplicated too much. Keep it small and use backend-compatible field names/order.
- Large sheets may reallocate many rows on each input event. Debounce ĐM input or reallocate on blur/input with a short debounce if needed.
- Data Hub `/bcct/by-codes` must be reliable for fast stock lookup on large clients. Without it, ĐM-only allocation preview may be slow or incomplete.
- Hidden form inputs for allocation rows are currently server-rendered. Live-created child rows are visual; final export relies on backend recompute after save. Do not use unsaved live child rows for export.

## Open Questions

- Should shortage still allow `Lưu bảng kê`, or should save be blocked client-side when required qty cannot be covered?
- For mixed currency, should the live UI show "mixed" immediately or simply defer exact valuation to backend?
- Should ĐM input reallocate on every keystroke or only after debounce/blur to avoid noisy UI on big sheets?

## Recommended Next Step

Implement directly with focused tests:

- browser regression for replace with multi-lot child rows;
- browser regression for ĐM edit rebuilding child rows;
- browser regression for add row creating child rows;
- unit/backend tests stay around save/recompute because backend remains authoritative.
