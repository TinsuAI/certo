# Session Log: CO Docs And Confirmation Template

## What Was Done
- Answered a series of business-logic questions around how the CO workbook allocates and tracks material usage.
- Moved from inference to direct inspection of the legacy `.xlsm` internals and confirmed:
  - `X-N` is the central allocation sheet
  - `Save` is the forward allocation ledger
  - `Tru lui` is the reverse/residual ledger
  - stock is tracked at source-row level, not just by aggregate material code
- Updated project-facing docs to reflect that the workbook models `CO stock`, not physical inventory.
- Examined completed dossiers and extracted concrete origin-qualification patterns:
  - Growatt `RVC 35% + CTSH`
  - Do Thanh `CTSH`
  - Hong An `CTH`, `CC`, `PSR`
- Wrote new/updated docs in `docs/`:
  - `docs/origin-qualification-case-studies.md`
  - `docs/co-input-output-model.md`
  - updates to `docs/workbook-business-logic-foundation.md`
  - updates to `docs/co-knowledge-base.md`
  - updates to `docs/README.md`
- Reworked Markdown formatting in the new docs so nested lists render more predictably.
- Checked `BCQT-System` as a reference project and located:
  - `docs/BUSINESS_LOGIC_CONFIRMATION.md`
  - `docs/BUSINESS_LOGIC_CONFIRMATION.docx`
  - `docs/BUSINESS_LOGIC_CONFIRMATION_v2.docx`
  - `docs/BUSINESS_LOGIC_CONFIRMATION_v3.docx`

## Decisions Made
- The future CO system should treat origin determination as a configurable multi-rule engine.
- `Vietnam origin` in practice must be modeled as rule-based qualification under the applicable agreement/form, not as a simplistic “all inputs are domestic” concept.
- The target domain should keep these layers distinct:
  - trader profile registration
  - reusable product-origin evidence
  - shipment-level filing
  - internal allocation/rule evaluation
  - issuance/archive outputs
- `CO stock` and `physical inventory` should remain separate concepts in the future system.

## What Didn't Work
- Pulling structured legal excerpts from some upstream PDF URLs was unreliable because several official links returned HTML or inaccessible binary responses.
- The `BCQT-System` reference step only reached artifact discovery in this session; the actual `.docx` rendering implementation was not yet traced.
- Two exploratory subagents used for the `BCQT-System` reference were closed before producing useful final summaries.

## Open Items
- Inspect the actual `.docx` rendering code in `BCQT-System` and copy the approach for this project.
- Draft a CO-specific business-logic confirmation document for agency validation, analogous to `BUSINESS_LOGIC_CONFIRMATION`.
- Commit the current `docs/` changes once grouped appropriately.
- Validate the current CO business-logic assumptions with the agency, especially around:
  - shipment vs product evidence reuse
  - source-row allocation semantics
  - which origin rules/form families matter first
