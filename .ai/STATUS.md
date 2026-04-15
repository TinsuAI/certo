# Project Status

## Current State
- Repo remains a discovery-first workspace for the CO domain, with shared business and analysis docs in `docs/`.
- The legacy `.xlsm` workbook has now been validated more concretely at sheet/XML level for allocation behavior, not only inferred from sheet names or VBA module names.
- `docs/workbook-business-logic-foundation.md` now records that workbook stock is tracked as a CO eligibility ledger at source-row level, not as aggregated material stock and not as physical inventory.

## Recent Changes
- Confirmed by direct workbook inspection that allocation stock is tracked per `import declaration number + import line number + material code`.
- Confirmed that `Save` persists forward allocations tied to `TKX`, while `Tru lui` keeps reverse/residual balances per source row.
- Clarified in project docs that `Tồn` in the workbook means remaining CO-available quantity, not warehouse on-hand inventory.
- Committed the project-facing doc update in `d012960` `Clarify workbook allocation stock model`.

## Next Steps
- Map the exact field-level semantics of `X-N`, including how `Số lượng XUẤT`, `SL sử dụng`, and helper columns interact during row splitting.
- Validate with operators whether source-row grain is always `import declaration + line + material`, or whether invoice-only rows and domestic-source rows follow a parallel pattern.
- Decide how the future system should reconcile `CO stock` with optional `physical inventory` snapshots without turning into a warehouse system.
- Continue translating workbook structures into explicit domain entities and services for system design.

## Notes for Next AI Session
- `data/` is local-only and gitignored.
- Correct host wiki path is `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources`.
- The user wants project knowledge in `docs/`; `.ai/` is only for AI working context and handoff.
- Important domain decision: keep `CO stock` and `physical inventory` separate in the future design. The legacy workbook only models the former.
