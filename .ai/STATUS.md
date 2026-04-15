# Project Status

## Current State
- Repo remains a discovery-first workspace for the CO domain.
- The business-logic understanding is materially deeper now: workbook allocation has been verified from real sheet/XML data, completed dossiers have been mined for real origin-rule cases, and the project docs now distinguish `CO stock` from `physical inventory`.
- New project-facing docs have been drafted but are still uncommitted in `docs/`.

## Recent Changes
- Verified from the workbook that allocation stock is tracked at source-row grain, effectively `import declaration + line + material code`, and documented that as a CO eligibility ledger model.
- Added case-based origin-rule documentation showing completed dossiers qualifying goods as Vietnam-originating under rules such as `RVC 35% + CTSH`, `CTH`, `CTSH`, `CC`, and `PSR`.
- Added a detailed `CO Input/Output Model` document that separates:
  - trader profile registration
  - reusable product-origin evidence
  - shipment-level filing
  - origin evaluation / allocation
  - issuance and audit outputs
- Referenced `BCQT-System` as the template source for a future CO business-logic confirmation document:
  - source doc found at `BCQT-System/docs/BUSINESS_LOGIC_CONFIRMATION.md`
  - generated outputs found at `BCQT-System/docs/BUSINESS_LOGIC_CONFIRMATION.docx`, `_v2.docx`, `_v3.docx`
- Adjusted Markdown formatting in the new docs so nested lists render more cleanly.

## Next Steps
- Review `BCQT-System` rendering code and reproduce an equivalent `.docx` pipeline for a CO-side business-logic confirmation document.
- Draft the CO equivalent of `BUSINESS_LOGIC_CONFIRMATION.md` for agency review, using the new case-study and input/output docs as source material.
- Decide which current doc changes should be committed together as the next project-facing docs commit.
- Continue refining field-level semantics for `X-N`, `Save`, and `Tru lui` only after operator validation is available.

## Blockers
- The new `docs/` changes are not yet committed:
  - `docs/README.md`
  - `docs/co-knowledge-base.md`
  - `docs/workbook-business-logic-foundation.md`
  - `docs/co-input-output-model.md`
  - `docs/origin-qualification-case-studies.md`
- The `.docx` render implementation from `BCQT-System` has not yet been inspected in detail, only the source/output artifacts have been located.

## Notes for Next AI Session
- `data/` is local-only and gitignored.
- Correct host wiki path is `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources`.
- The user wants project knowledge in `docs/`; `.ai/` is only for AI working context and handoff.
- Important domain decisions now reflected in docs:
  - keep `CO stock` and `physical inventory` separate
  - treat origin qualification as a configurable multi-rule engine, not a single formula
  - treat shipment filing, product evidence, and trader profile as separate layers
