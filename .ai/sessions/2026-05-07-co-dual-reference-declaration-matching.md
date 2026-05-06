# Session: C/O Dual Reference Declaration Matching

Date: 2026-05-07

## What Was Done

- Fixed invoice preview layout in the C/O create form.
  - The preview grid no longer overflows into adjacent controls.
  - When a preview exists in the overview create form, it spans the full form row.
- Reviewed and finalized the C/O shipment reference decision with the user.
  - Invoice can be wrong, missing, or inconsistent.
  - Export declaration is more authoritative when present because it points directly to reviewed BCCT export rows.
- Implemented dual shipment references.
  - `shipment.invoice_no` remains optional.
  - `shipment.export_declaration_nos` was added and normalized.
  - Existing records default missing declaration references to an empty list.
- Implemented declaration-authoritative BCCT matching.
  - File-backed matching now prefers `declaration_no` when export declarations exist.
  - Invoice-only dossiers still match by `invoice_ref`.
  - If invoice and declaration disagree, matching follows the declaration and emits a warning.
  - If a declaration row has no `invoice_ref`, the dossier can still proceed and emits a warning.
  - Postgres source-index matching accepts export declaration refs, normalizes declaration formatting/case, and checks adapter capability without swallowing internal `TypeError`s.
  - Data Hub mode uses already available BCCT list rows for declaration-authoritative matching; no new Data Hub endpoint was added.
- Updated the C/O UI.
  - Create form now has separate `Invoice` and `Số tờ khai xuất` fields.
  - Shipment step persists and displays both references.
  - Exports/origin wording now says “tham chiếu hồ sơ” where invoice-only wording was misleading.
  - Export match table shows reference warnings.
- Updated workbook export.
  - Case sheet includes export declarations.
  - BCCT match sheet includes match source and warning columns.
- Added regression tests for declaration-first behavior and legacy invoice behavior.
- Verification:
  - targeted invoice/declaration tests passed
  - full suite passed: `179 passed in 33.92s`
  - health check returned `{"status":"ok"}` on port `8001`

## Decisions Made

- Use dual reference, declaration-authoritative when present.
- Do not treat invoice as the sole CO case key.
- Keep invoice as a useful optional field for document identity and fallback lookup.
- When both invoice and declaration exist but disagree, do not block the dossier; use declaration rows and show a warning.
- Do not add or assume new Data Hub endpoints from CO. Declaration-based matching must use current adapter/source data unless a future approved Data Hub contract is created.
- Keep UI fields separate: one `Invoice` field and one `Số tờ khai xuất` field. Backend still tolerates a declaration pasted into the invoice field, but the UI should not suggest entering declarations in both places.

## What Didn't Work

- The initial quick fix mapped a declaration back to invoice during creation. That was insufficient because real BCCT rows may have missing or wrong invoice refs.
- The first UI wording made the invoice lookup say “Invoice hoặc số tờ khai” while a separate export declaration field also existed. This made the form look like it had two declaration inputs; the label was corrected back to `Invoice`.
- The first full test run after implementation failed because:
  - an existing test still asserted the old heading `BCCT xuất khẩu theo invoice`
  - a fake Postgres source index accepted only the old three-argument `match_bcct_exports` signature
  Both were corrected.
- A post-commit review found two important follow-ups:
  - Postgres declaration matching initially used raw exact `declaration_no`; it now normalizes both stored declaration and input key.
  - The source-index compatibility fallback initially caught all `TypeError`s; it now checks function signature before deciding which call shape to use.

## Open Items

- Manually review the create/shipment forms with real data for:
  - invoice-only cases
  - declaration-only cases
  - matching invoice + declaration
  - mismatched invoice + declaration
  - declaration rows with missing `invoice_ref`
- Decide whether multi-declaration or multi-invoice declaration cases need explicit row selection instead of automatic grouping.
- Confirm production completed-dossier status values for delete blocking.
- Decide whether global stock reservation/decrement should become a Data Hub-owned ledger later.
- Revisit mixed-currency allocation rules before summing VNM across currencies automatically.
