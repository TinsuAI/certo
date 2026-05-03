# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; unauthenticated requests redirect to `/auth/login`.
- Sibling Data Hub dev server responds at `http://127.0.0.1:8754` (`/health` currently returns `404`, but the server is reachable).
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- This session was research/documentation only; no application code was changed.
- Legacy `tru lui CO final ...xlsm` output sheet structure is now documented in `docs/legacy-workbook-output-sheet-structure.md`.
- Origin calculation workflow risks are summarized in `.ai/features/2026-05-04-co-origin-calculation-workflow.md`.
- Pre-existing untracked artifacts remain separate and should not be committed unless explicitly requested:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`

## Recent Changes
- Investigated the legacy workbook/macro calculation path for value-content sheets.
- Confirmed the workbook uses build-down/indirect calculation for `M1607`: `(FOB - non-origin value) / FOB * 100`.
- Confirmed direct labor and direct allocation costs are calculated for the price/cost explanation footer, not for the final RVC/LVC percentage.
- Identified source of direct cost values: template/input coefficient cells `P1590`, `P1591`, `P1595`, `P1596`, and `P1597`, multiplied by `K10`.
- Inspected output templates `LVC`, `RVC`, `CTH`, `CTSH`, and `EUR1`, including body columns, helper columns, footer blocks, hidden rows, print areas, and export ranges.
- Documented the legacy export strategy: copy the template sheet, fill values, hide empty rows/helper columns, then paste values over the copied range to preserve formatting.

## Next Steps
1. Use `docs/legacy-workbook-output-sheet-structure.md` as the reference when implementing generated bang ke Excel export.
2. For exact Excel parity, preserve template sheets and fill/copy values instead of rebuilding styles manually.
3. Decide product behavior for criteria modes: build-down RVC/LVC, direct/build-up, `CTH`, `CTSH`, `EUR1/PSR`, and compound rules.
4. Do not implement build-up/direct formulas until the required `VOM`, direct labor, overhead, profit, and agreement-specific inclusion rules are modeled explicitly.
5. For `CTH/CTSH`, do not assume the macro proves HS rule evaluation. The legacy macro mostly exports the template and conclusion; a real evaluator still needs to compare product/material HS according to the selected rule.

## Blockers
- Direct/build-up value-content calculation is not implemented in the app or clearly present in the legacy workbook logic.
- The legacy workbook's direct cost coefficients appear to be preset/input template values, not derived from BOM or Data Hub.
- Durable allocation/evidence for originating material values and supplier declarations is still required before direct/build-up or stronger LVC/RVC evidence can be implemented safely.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to hidden business logic. Briefly explain what was inspected, what was tried, and what conclusion is evidence-backed.
- The five relevant legacy output sheets are `LVC`, `RVC`, `CTH`, `CTSH`, and `EUR1`.
- `LVC/RVC` visibly show value-content calculation; `CTH/CTSH` hide the value-content footer and show tariff-shift conclusions; `EUR1` adds an EXW/coefficient block around rows `1610:1615`.
- Keep Data Hub API literals inside `app/data_hub_client.py`.
- Do not commit or modify the pre-existing untracked `.ai/features/2026-05-02-*` files or `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md` unless asked.
