# Feature: Design Foundation From Workbook Logic

## Scope
Create the documentation needed to start system design from the current CO workbook, local case files, and knowledge base. This includes consolidating workbook workflow, business logic, legal constraints, and architecture implications into one design-facing document.

Out of scope:
- UI design
- implementation planning
- field-by-field workbook reverse engineering
- live operator validation

## Decisions
- Treat the `.xlsm` workbook as a business-rule engine, not as a mere spreadsheet attachment.
- Treat legal and filing requirements from the V-Notes knowledge base as current regulatory context.
- Organize the design foundation around workflow, state, allocation logic, rule evaluation, and auditability.

## Risks
- Some workbook rules may still be hidden in legacy VBA paths or hidden sheets.
- Historical ledger semantics in `Save` and `Tru lui` may be misunderstood without operator walkthrough.
- Current local documents may mix legacy and current regulatory practice.

## Open Questions
- Which macro path is the real production path today?
- What historical state must be migrated for a trustworthy first system release?
- Which form families are the first design target?
