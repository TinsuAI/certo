# Session: Legacy Workbook Output Structure

## What Was Done
- Refreshed project context and confirmed the CO dev server is running at `http://127.0.0.1:8001`.
- Investigated the legacy `tru lui CO final ...xlsm` workbook and extracted VBA to understand how origin/value-content calculations work.
- Confirmed the workbook's visible value-content result uses build-down/indirect logic:
  - `M1607 = Round((I1604 - K1606) / I1604 * 100, 2) & " %"`
  - `I1604` is FOB after incoterm handling.
  - `K1606` is the non-originating material total from `sumI`.
- Confirmed direct labor and direct allocation costs are used in the footer cost explanation:
  - `I1593 = I1590 + I1591`
  - `I1599 = I1595 + I1596 + I1597`
  - `I1600 = sumH + sumI + I1593 + I1599`
  - `I1601 = I1602 - I1600`
- Confirmed those direct costs do not feed the final `M1607` RVC/LVC percentage in the inspected workbook/macro.
- Identified direct cost sources as preset/input coefficient cells in column `P`:
  - `P1590`, `P1591`, `P1595`, `P1596`, `P1597`
  - The macro reads these cells and multiplies by `K10`; it does not calculate them from BOM.
- Inspected the five legacy output templates:
  - `LVC`
  - `RVC`
  - `CTH`
  - `CTSH`
  - `EUR1`
- Documented the output sheet/export structure in `docs/legacy-workbook-output-sheet-structure.md`, including export ranges, print area, row layout, material columns, helper columns, footer calculations, hidden rows, and sheet-specific differences.
- Added `.ai/features/2026-05-04-co-origin-calculation-workflow.md` summarizing current origin-flow risks and missing pieces for future direct/build-up support.

## Decisions Made
- Treat the legacy workbook export as a template-copy workflow, not a style-rebuild workflow. Exact parity should copy template sheets, write values, hide rows/columns, and preserve the workbook's formatting/page setup.
- Treat direct labor/direct allocation values as cost-explanation inputs until the product has a first-class cost model. They should not be silently used as direct/build-up RVC evidence.
- Treat `CTH` and `CTSH` as distinct output templates/conclusions, but do not assume the legacy macro is a real HS-rule evaluator. The macro fills the same BOM/value table and shows a tariff-shift conclusion.
- Treat `EUR1` as a special PSR output with an extra EXW/coefficient block at rows `1610:1615`.
- Do not implement direct/build-up formula support until `VOM`, labor, overhead, profit, other costs, and agreement-specific inclusion rules are explicitly modeled.

## What Didn't Work
- A direct workbook inspection with heavier workbook tooling was slow and was abandoned; direct OOXML parsing was used instead to inspect sheet names, dimensions, cell values, hidden rows, print areas, and formulas efficiently.
- Searching the workbook/VBA did not find an active direct/build-up RVC calculation path. The only active final percentage formula found was build-down/indirect.
- The legacy `LVC` sheet/sample conclusion has inconsistent text that still says `RVC <percent> + CTSH`; preserve this as a legacy observation, not as a product rule.

## Open Items
- Implement generated bang ke/export using `docs/legacy-workbook-output-sheet-structure.md` as the parity reference.
- Decide how the app should choose or expose criteria modes: build-down RVC/LVC, direct/build-up, CTH, CTSH, EUR1/PSR, and compound criteria.
- Build a real `CTH/CTSH` evaluator if tariff-shift decisions must be system-generated rather than carried from selected criteria.
- Model direct/build-up inputs explicitly before using them in origin qualification.
- Keep pre-existing untracked artifacts separate unless the user asks to include them:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`
