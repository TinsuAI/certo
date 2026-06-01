# Feature: C/O Workflow Navigation Redesign

## Scope

Redesign the C/O area so it matches the operator mental model: C/O is the primary shipment workflow, while catalog, BOM, C/O stock, BCCT, and config are supporting data surfaces.

This change will:
- remove C/O from the same peer tab row as data-source modules
- introduce a primary "Làm hồ sơ C/O" entry point in the client workspace
- split a selected C/O dossier into workflow step views:
  - create/open dossier
  - shipment metadata
  - supporting documents
  - export declaration / invoice matching
  - origin evidence and allocation preview
  - review and dossier export
- keep existing persisted dossier routes compatible where practical
- keep current file-backed demo storage and current dossier workbook export

This change will not:
- implement final HS-specific PSR legal lookup
- mutate C/O stock or create a real allocation ledger
- implement eCoSys submission tracking
- change production architecture, auth, database, or deployment decisions
- add OCR or semantic PDF parsing

Visual thesis:
The C/O area should feel like a focused operator workflow: one main lane with numbered steps, dense evidence surfaces, and quiet supporting navigation.

Content plan:
- client header: company identity and a primary C/O workflow entry
- support modules: compact data-source tabs for catalog, BOM, C/O stock, BCCT, config
- C/O index: create/open dossiers and explain the step lane through operational labels
- selected dossier: persistent workflow step rail plus one active work surface per step

Interaction thesis:
- selected step is stable and obvious through a horizontal stepper
- step links deep-link to distinct URLs so operators can return to a specific point in the dossier
- primary actions stay near the active step instead of one large mixed page

## Decisions

- Treat C/O as the main application workflow for this demo, not as another source-data module.
- Keep the existing `/clients/{client_id}/co-case` entry URL as the C/O workflow index.
- Keep `/clients/{client_id}/co-case/{case_id}` compatible by resolving to the first selected dossier step instead of removing it.
- Add explicit step URLs under `/clients/{client_id}/co-case/{case_id}/{step}`.
- Use the existing `co_case.html` template with step-specific sections first; split into separate templates only if the file becomes hard to maintain.
- Preserve the current backend behaviors: dossier creation, supporting upload, invoice matching, criteria preview, evaluate, and XLSX export.
- Redirect supporting-file upload back to the documents step because that is the operator's current task context.
- Keep "needs_rule_lookup" visible in origin/review steps until a structured PSR engine exists.

## Risks

- Existing tests and manual links expect the detail route to show every C/O section at once; those should be updated to assert the new step URLs.
- If the page hides too much context, operators may lose the relationship between shipment docs, BCCT export rows, and origin evidence. The step header must keep dossier status visible.
- The current `evaluate` route is shared with the demo seed form. Step-specific views must not break persisted dossier metadata updates.
- Making C/O visually primary could obscure data maintenance tasks. The navigation should still expose support modules clearly as data surfaces.
- The current criteria preview is not real allocation. The UI must label it as preview and avoid implying stock has been reserved.

## Open Questions

- Should the final production workflow include separate submission/issuance/archive steps, or is review/export enough for this demo sprint?
- Should product-origin evidence become its own long-lived area separate from shipment C/O after this UI pass?
- When allocation is implemented, should the "origin evidence" step split into rule evaluation and stock reservation?
- Should the workflow step completion status be calculated from persisted state or remain lightweight until the dossier state model is expanded?
