# Workbook Business Logic Foundation

## Purpose
This document describes the business logic needed to design a software system that can replace or absorb the current Excel-based CO process.

Detailed supporting materials:
- [Procedure And Workbook Analysis](./procedure-and-workbook-analysis.md)
- [CO Knowledge Base](./co-knowledge-base.md)
- [Data Exploration](./data-exploration.md)

## System Problem Statement
The current process has two tightly coupled layers:

1. A compliance workflow layer
   Enterprise registration, dossier preparation, form selection, origin proof, eCoSys submission, issuance, and archive.

2. A stateful allocation / calculation layer
   Implemented today in the workbook. It allocates export demand against source material history, computes rule-specific evidence, and maintains long-lived ledgers of prior usage.

The future system must cover both.

## Business Workflow

### Layer A. Trader profile registration
This is company-level setup on eCoSys.

Required information:
- enterprise identity
- business and tax registration
- seal sample
- authorized signature sample
- production facility information

This should happen once, then be maintained when enterprise facts change.

### Layer B. Product-origin evidence registration
For each stable product or product family, the business prepares reusable origin-supporting evidence such as:
- BOM
- manufacturing process
- criteria sheets
- supplier/manufacturer declarations
- domestic input evidence
- imported input support evidence

This layer is product-oriented, not shipment-oriented.
It is the evidence base reused for later shipments when the product is stable.

### Layer C. Shipment-level C/O filing
For each shipment / lô hàng, the business files a shipment-specific dossier:
- application form
- C/O form
- export declaration
- invoice
- packing list
- transport document
- links to the relevant product-origin evidence

This is the actual per-shipment filing event.

## Reuse Rule For Same Product
If two shipments contain the same fixed product:
- the trader profile is not re-registered
- the shipment still needs a separate C/O filing
- the full product-origin evidence should not need to be rebuilt from scratch each time if still valid

Practical interpretation for system design:
- a shipment references a reusable `ProductOriginEvidenceVersion`
- evidence has validity and change history
- shipment docs are always per-shipment

Typical legal/operational reading from the current procedure:
- the first filing for a new or newly exported product needs the full origin-supporting dossier
- later filings for the same fixed product can reuse the product-origin evidence
- reusable evidence such as criteria declaration, supplier/manufacturer declaration, and production process documentation is commonly treated as valid for `2 years`, unless the underlying facts change and must be re-submitted

## Workbook Logic Model

### Intake
- `NK`
  Raw import customs data
- `NK2`
  Import normalization layer
- `XK`
  Export source layer

### Run selection
- `DM`
  Current grouping / run selector
- `Xuat`
  Export selection sheet

### Allocation
- `X-N`
  Central matching and row-splitting sheet
- `Save`
  Historical usage ledger
- `Tru lui`
  Reverse / decrement / reconciliation ledger

### Rule output
- `Chiphi`
- `LVC`
- `RVC`
- `EUR1`
- `CTH`
- `CTSH`
- hidden output sheets such as `WOIII`, `FORM B`, `FORM X`, `PTN`

## Business Capabilities The System Must Support

### 1. Registration and profile management
- maintain enterprise profile
- maintain signatory / seal / production facility data
- track eCoSys readiness

### 2. Shipment dossier management
- create shipment case
- collect shipment-specific docs
- track missing docs
- tie shipment to target form family and agreement

### 3. Product-origin evidence management
- version BOM and manufacturing process
- version supplier / origin declarations
- track evidence validity window
- track when evidence changes require re-submission

### 4. Allocation engine
- reconcile export demand against source-material history
- split partial quantities
- record carry-forward
- preserve historical allocations
- support reverse / adjustment logic

### 5. Origin rule engine
- support `WO`, `CTC`, `RVC`, `LVC`
- support rule-specific outputs and evidence sheets
- make pass/fail and supporting explanation reviewable

### 6. Filing and issuance tracking
- prepare eCoSys-ready case
- track submission, correction, issuance, and inspection
- store issued result and archive

### 7. Auditability
- retain evidence for at least the compliance retention period
- reconstruct how each issued shipment was supported
- trace import/source records used in each origin evaluation

## Legal And Compliance Requirements

### Current authority and platform
- MoIT is the current issuing authority
- eCoSys is the filing platform
- digital signature is required

### Timing
- trader profile registration: about `6-12 hours` / `1 working day`
- standard valid application: up to `3 working days`
- inspection case: up to `5 working days`
- paper-form lane: around `1 day`
- e-form lane: around `3 days` for general goods and `7 days` for electronics

### Origin logic constraints
- imported inputs are non-originating
- value-based rules depend on FOB and non-origin / imported input value
- paper form and electronic form are distinct operational lanes

### Retention
- evidence and related records should be retained for at least `5 years`

### Reusable product-evidence window
- reusable origin-supporting documents for fixed products should be modeled with a validity window, currently interpreted from the procedure as `2 years`

## Candidate Domain Model
- Company
- TraderProfile
- AuthorizedSignatory
- SealSample
- ProductionFacility
- Product
- ProductOriginEvidence
- ProductOriginEvidenceVersion
- Shipment
- ShipmentDocument
- COCase
- COFormFamily
- Agreement
- ExportDeclaration
- ImportDeclaration
- AllocationRun
- AllocationRecord
- ReverseLedgerRecord
- OriginRuleEvaluation
- EvidenceSheet
- FilingSubmission
- IssuedCO
- AuditRecord

## Open Questions
- Which macro path is the production path today: `RunUpgrade` or legacy runs?
- What is the exact semantic meaning of the grouping key generated in `DM`?
- Are `Save` and `Tru lui` global ledgers per company, per workbook clone, or per period?
- Which form families should be covered in the first system release?
- How much historical state must be migrated before operators trust the new system?
