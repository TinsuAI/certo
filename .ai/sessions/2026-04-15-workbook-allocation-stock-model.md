# Session Log: Workbook Allocation Stock Model

## What Was Done
- Answered follow-up questions about allocation logic in the workbook around `X-N`, `Save`, and `Tru lui`.
- Moved from inference to direct inspection of the `.xlsm` internals by unpacking the workbook and reading sheet XML content for `NK2`, `X-N`, `Save`, and `Tru lui`.
- Confirmed that the workbook tracks CO-available balances per import-source row rather than by aggregated material code only.
- Confirmed that the operational grain is at least `import declaration number + import line number + material code`, with `TKX` linking each allocation to an export run.
- Updated `docs/workbook-business-logic-foundation.md` to capture the verified stock model and the distinction between `CO stock` and `physical inventory`.

## Decisions Made
- Treat the workbook stock model as a source-row-level CO eligibility ledger.
- Do not describe the workbook as managing physical inventory unless direct evidence appears later.
- Keep `CO stock` and `physical inventory` separate in the target system design, with reconciliation as an optional capability rather than a shared source of truth.

## What Didn't Work
- Earlier explanations relied partly on inference from sheet/module names. The user pushed for direct verification, so OOXML-level inspection was used instead.
- The workbook is too large for casual full reads; targeted extraction of relevant sheets worked better than broad inspection.

## Open Items
- Verify whether all source rows are always import-declaration based, or whether domestic inputs and VAT-invoice sources follow additional patterns.
- Extract the exact semantics of helper columns and composite keys inside `X-N`, `Save`, and `Tru lui`.
- Decide what minimum physical-inventory reconciliation, if any, belongs in the first system design.
