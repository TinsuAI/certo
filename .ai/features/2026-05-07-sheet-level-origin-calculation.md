# Feature: Sheet-Level Origin Calculation

## Scope

Change the C/O origin workflow from one global "Tính lại snapshot" action to product-sheet-level calculation and locking.

In scope:
- Replace drag/drop sheet ordering with explicit left/right arrow controls on each sheet tab.
- Remove the global `Tính lại snapshot` action from the origin workbar.
- Add `Tính bảng kê` inside each product sheet.
- Persist case state after each sheet-level action: order changes, BOM selection changes, sheet calculation, and sheet status changes.
- Add per-sheet statuses for origin calculation workflow:
  - `draft` / `chưa tính`: sheet has source data but no current calculated statement.
  - `calculating` / `đang tính`: transient UI state during request.
  - `calculated` / `đã tính`: sheet has a current calculated statement, but is not locked/final.
  - `locked` / `chốt`: sheet statement is accepted and should not mutate unless explicitly reopened.
  - `stale` / `cần tính lại`: sheet depends on changed upstream order/BOM/material inputs.
- Preserve sequential stock logic: calculating sheet N must use committed/current outputs from sheets before N, then mark sheet N and later sheets according to dependency changes.

Out of scope for this pass:
- Data Hub global stock reservation/decrement ledger.
- Multi-user collaborative editing beyond the existing customer-level calculation lock.
- New Data Hub endpoints.
- Final submitted/completed dossier workflow; this is origin-preparation state only.

## Decisions

- Use arrow buttons instead of drag/drop for ordering. The user-facing mental model is "move this sheet earlier/later", not freeform dragging.
- Sheet tabs remain the source of truth for visible order. There should be no separate order table.
- Global export still requires the relevant sheets to be current and not stale. Export should not silently recalculate all sheets.
- Per-sheet status should live inside the persisted case record, likely under `origin_sheet_states` keyed by product code or stable product line identity.
- The calculation endpoint should become sheet-scoped, for example:
  - `POST /clients/{client_id}/co-case/{case_id}/origin/sheets/{product_code}/calculate`
  - `POST /clients/{client_id}/co-case/{case_id}/origin/sheets/{product_code}/lock`
  - `POST /clients/{client_id}/co-case/{case_id}/origin/sheets/{product_code}/reopen`
- Autosave can reuse `update_case_record()` rather than introducing a separate storage layer.

## Risks

- Sequential allocation is not independent per sheet. If sheet 1 changes, sheet 2+ stock opening quantities and shortage traces become stale. The UI must make this obvious and prevent exporting stale downstream sheets.
- Current `prepare_case_origin_products()` rebuilds all products against a fresh stock pool. A sheet-level endpoint needs either:
  - a controlled full recomputation with sheet status preservation, or
  - a new helper that computes up to sheet N and invalidates downstream sheets.
- Product code alone may not be stable enough if one dossier can contain the same product code on multiple export rows. If duplicates are possible, use product line identity from declaration/line/code rather than only product code.
- Existing customer-level origin calculation lock still matters. Sheet-level calculation should acquire/renew the same lock so two dossiers for one customer cannot consume the same local stock view concurrently.
- Autosave increases write frequency to local case state. Writes are file-locked today, but UI should avoid saving on every keystroke; save on deliberate actions and field blur/change.
- "Chốt" needs a reopen path. Otherwise users can get stuck after noticing a BOM or định mức issue.

## Open Questions

- Should `Chốt` be per sheet only, or should there also be a dossier-level "chốt toàn bộ bảng kê" later?
- If a locked sheet before N is reopened and recalculated, should all downstream locked sheets automatically become `stale`, or should the app block reopening until downstream sheets are reopened first?
- Can a dossier contain duplicate finished-product codes across multiple export declaration rows? If yes, sheet identity must include declaration/line.
- Should export require every sheet to be `locked`, or is `calculated` enough for draft XLSX export?
- Should changing BOM on a locked sheet force `reopen` first, or automatically move it back to `stale`?

## Suggested Next Step

Use TDD before implementation. Start with case-store and route tests for:
- arrow reorder persists immediately and marks affected sheets stale,
- calculating one sheet updates only that sheet status while invalidating downstream,
- locked upstream sheet prevents accidental edit or requires explicit reopen,
- export blocks stale sheets and respects the existing customer-level calculation lock.
