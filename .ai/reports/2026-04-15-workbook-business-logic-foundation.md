# Workbook Business Logic Foundation

## Purpose
This document consolidates the operational workflow, workbook logic, knowledge-base findings, and legal/compliance constraints required to design a software system that can replace or absorb the current Excel-based CO process.

It is not a UI spec and not an implementation plan. Its purpose is to describe the business logic clearly enough that system design can begin from a stable understanding of the domain.

## Source Map

### Primary local artifacts
- [Procedure and Workbook Analysis](./2026-04-15-procedure-workbook-analysis.md)
- [Data Exploration Report](./2026-04-15-data-exploration.md)

### Knowledge base
- [CO Notes From V-Notes](../knowledge/2026-04-15-co-notes-from-v-notes.md)

### Raw source files behind the analysis
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/QUY TRÌNH XIN CẤP CO.pdf`
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/Lưu trình xin CO.jpg`
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/tru lui CO final  SXXK - 2025 commercial-MAC - Huyền đúng.xlsm`

## Executive Summary
The current CO operation has two tightly coupled layers:

1. A compliance workflow layer.
   This covers enterprise profile registration, dossier assembly, form selection, origin-rule justification, eCoSys submission, issuance, and audit retention.

2. A stateful calculation and allocation layer.
   This is implemented today in the `.xlsm` workbook. It allocates export demand against import/declaration history, computes rule-specific evidence sheets, records historical consumption, and prepares printable submission artifacts.

The workbook is therefore not a convenience spreadsheet. It is an operational rule engine for:
- traceability
- allocation
- origin-rule calculation
- case packaging
- audit persistence

Any future system that only manages files and form fields will underspecify the problem.

## What The Business Is Actually Doing

### 1. Registering the trader and filing context
Before normal CO issuance starts, the enterprise must register on eCoSys with:
- enterprise profile
- seal sample
- authorized signature sample
- business/tax registration information
- production facility information

Operational meaning:
- the system needs a persistent trader profile layer
- the system needs to distinguish first-time onboarding from normal shipment processing

### 2. Preparing a shipment dossier
For each CO case, staff gather:
- export customs declaration
- invoice
- packing list
- bill of lading / transport document
- C/O request form
- target C/O form family
- origin proof worksheets
- manufacturing process summary
- BOM / material norm
- import declarations for imported inputs
- domestic material purchase evidence or origin commitment

Operational meaning:
- a case is not just “one PDF package”
- a case is a bundle of shipment facts, evidence documents, product logic, and rule evaluation

### 3. Determining the filing lane
The business must choose:
- which form / agreement applies
- whether the lane is electronic or paper
- whether origin is justified by WO, CTC, RVC, LVC, or another rule family
- whether the shipment needs extra verification

Operational meaning:
- form choice, rule choice, and filing mode are separate concepts and should not be collapsed into one field

### 4. Proving origin
This is the hardest part operationally.
The team must show that exported goods qualify under the relevant origin criterion by tying:
- export goods
- product code or declaration grouping
- BOM / manufacturing process
- imported input history
- domestic input evidence
- cost / value evidence

Operational meaning:
- the software must support origin proof as a computed, reviewable object
- not just as a file attachment

### 5. Filing and issuance
The dossier is filed through eCoSys with digital signature, reviewed by the issuing authority, then either issued, delayed, corrected, or inspected.

Operational meaning:
- the future system needs a filing lifecycle and submission status model

### 6. Retention and auditability
After issuance, the case remains compliance evidence. Records must be retained and traceable.

Operational meaning:
- archive is part of the core product, not an afterthought

## Workbook As System

## Role of the workbook
The workbook is a stateful, macro-enabled operating system for CO preparation.
It is used to:
- normalize import and export data
- select the current export run
- reconcile export demand against historical import usage
- maintain a running consumption ledger
- generate criteria-specific worksheets
- generate printable or PDF-ready outputs

It also contains:
- machine-level access control via MAC check
- time-lock logic
- hidden sheets used as template or output support layers

This strongly suggests it is an internal controlled tool, not a generic spreadsheet distributed casually.

## Workbook architecture

### Input / staging layer
- `NK`
  Raw import-side customs data
- `NK2`
  Processed import layer derived from `NK`
- `XK`
  Export-side source data
- `DM`
  Current grouping / selector / normalization layer for the current CO run
- `Xuat`
  Export selection sheet fed by `DM`
- `X-N`
  Central staging sheet where export demand is matched to available material history

### Ledger layer
- `Save`
  Historical fact table of prior allocations / prior usage
- `Tru lui`
  Reverse / decrement ledger used for reconciliation and carry-forward logic

### Cost / rule layer
- `Chiphi`
  Cost sheet or compact cost summary input
- `LVC`
- `RVC`
- `CTH`
- `CTSH`
- `EUR1`
- `WOIII`
- `FORM B`
- `FORM X`
- `PTN`

These sheets represent different output or rule-specific evidence forms.

## Workbook pipeline

### Stage 1. Import-side normalization
`NK` is the raw import customs base.
Macros such as `layDataNK` / `layDataNKArr` transform this into `NK2`.

Interpretation:
- import declaration history is not used directly
- it is normalized before matching

### Stage 2. Export-side intake
`XK` holds export-side data used by the output templates.
The criteria sheets read dates, values, incoterms, and export declaration details from `XK`.

Interpretation:
- `XK` is the export truth source for the current run

### Stage 3. Current run selection
`DM` determines which grouping or export batch is currently being processed.
The workbook appears to derive a run key or grouping key in `DM!K6`, then propagates it into `NK2!V3` and `Xuat!B1`.

Interpretation:
- a “CO run” is an explicit selection context
- the system will need a first-class concept for run scope or shipment scope

### Stage 4. Export-to-import matching
`X-N` is the central matching sheet.
This is where the workbook appears to:
- copy selected export rows
- compare required quantities against available import/material history
- split rows when available stock and required usage differ
- carry remainder logic across rows
- build helper keys

Interpretation:
- this is the heart of inventory netting / allocation logic
- future system design should treat allocation as its own engine, not as spreadsheet residue

### Stage 5. Persisting history
`Save` receives fulfilled `X-N` rows and stores them as historical usage records.
The workbook builds composite lookup keys in `Save` so later output sheets can reconstruct provenance and prior consumption.

Interpretation:
- `Save` is the canonical usage ledger in the current workbook architecture

### Stage 6. Reverse / carry-forward logic
`Tru lui` appears to be the reverse-deduction ledger.
It validates totals, checks duplicates, and tracks remaining or consumed material quantities.

Interpretation:
- future system needs both:
  - forward allocation records
  - reverse / adjustment / reconciliation records

### Stage 7. Generating rule sheets and output forms
Macros such as:
- `Run1`
- `Run2`
- `Run3`
- `RunUpgrade`
- `XoaLVC`
- `XoaRVC`
- `XoaCTH`
- `XoaCTSH`
- `Inctu`
- `xuatCtu`

prepare the criteria-specific sheets and printable artifacts.

Interpretation:
- rule evaluation and document output are coupled today
- the future system should separate:
  - evaluation engine
  - document rendering engine

## Core Business Logic Encoded By The Workbook

### 1. Composite identity logic
The workbook uses composite keys built from multiple business fields rather than a single natural ID.

Why this matters:
- shipment data alone is not enough
- matching seems to rely on declaration number + sequence + product/material grouping

System implication:
- the future system needs explicit normalized IDs and stable surrogate IDs
- but also must preserve the business composite keys used in legacy traceability

### 2. Allocation logic
The workbook does not merely list source documents.
It allocates input history to output demand.

Allocation behavior appears to include:
- partial consumption
- row splitting
- leftover carry-forward
- duplicate checks
- reconciliation against historical use

System implication:
- allocation must be a core service / domain module
- not a report query

### 3. Historical dependency
The workbook is stateful because current calculations depend on prior allocations in `Save` and `Tru lui`.

System implication:
- a case cannot always be calculated in isolation
- the system must preserve period history and prior usage history

### 4. Rule-specific evidence generation
The workbook supports multiple origin-rule or form families:
- `LVC`
- `RVC`
- `CTH`
- `CTSH`
- `EUR1`
- hidden output families such as `FORM B`, `FORM X`, `PTN`, `WOIII`

System implication:
- the system needs a rule abstraction layer
- each rule should specify:
  - required inputs
  - computation method
  - evidence output structure
  - target form family

### 5. Cost and value integration
The workbook references:
- FOB
- non-origin value
- local/regional value
- cost components
- incoterms
- export value

System implication:
- origin evaluation depends on value model, not only document presence

### 6. Print and packaging logic
The workbook can generate output workbooks and export PDFs.

System implication:
- case assembly should likely produce:
  - structured evaluation records
  - evidence sheets
  - submission-ready bundles
  - archive-ready issued bundles

## Legal And Compliance Requirements

### 1. Issuing authority
From the knowledge base:
- MoIT is the centralized issuing authority from `May 2025`
- legacy materials may still reference VCCI, but product design should assume the current authority model

### 2. Filing channel
From the knowledge base:
- eCoSys is the mandatory filing channel
- digital signature is required

### 3. Turnaround expectations
From the knowledge base and local procedure artifacts:
- trader profile registration: `6-12 hours` or about `1 day`
- valid application issuance: up to `3 working days`
- on-site inspection case: up to `5 working days`
- paper forms: around `1 day`
- e-form general goods: around `3 days`
- e-form electronics: around `7 days`

### 4. Origin rules
The system must support at least the concepts summarized in the knowledge base:
- `WO`
- `CTC`
- `RVC`
- `LVC`

Captured formulas:
- `RVC = (FOB - non-origin material value) / FOB × 100%`
- `LVC = (FOB - CIF value of imported or undetermined-origin inputs) / FOB × 100%`

### 5. Treatment of imported inputs
Imported materials are treated as non-originating in origin calculations, even when duty-exempt.

Design implication:
- import status and origin status are not the same thing
- duty-free input is not automatically originating input

### 6. Retention
The knowledge base records a `5-year` record-retention requirement for C/O-related evidence.

Design implication:
- document retention and immutable audit trail need to be first-class requirements

## Actors And Responsibilities

### Import-Export team
- determine form type
- prepare shipment-side dossier
- prepare export declarations and supporting shipping docs
- hand off to consultant or compliance operator
- archive approved case

### Accounting / operations
- prepare BOM / material norm
- maintain invoice evidence
- support cost/value evidence

### Consultant / compliance operator
- review case completeness
- advise on first-time registration and form selection
- complete criteria sheets
- finalize filing package
- update paper/electronic C/O artifacts
- archive issued case

### Issuing authority
- receive filing via eCoSys
- review dossier
- issue / reject / request clarification
- inspect if needed

## Candidate Domain Model

### Core entities
- Company
- TraderProfile
- AuthorizedSignatory
- SealSample
- ProductionFacility
- COCase
- Shipment
- ExportDeclaration
- ExportDeclarationLine
- ImportDeclaration
- ImportDeclarationLine
- Product
- Material
- CodeMapping
- UnitOfMeasure
- UnitConversionRule
- BOM
- BOMLine
- SupportingDocument
- OriginRuleEvaluation
- AllocationRun
- AllocationRecord
- ReverseLedgerRecord
- FilingSubmission
- IssuedCO
- AuditRetentionRecord

### Supporting concepts
- FormFamily
- FilingMode
- Agreement / TradeScheme
- EvidenceSheet
- ComplianceIssue
- CaseStatus

## Candidate System Workflow

### Phase 1. Trader setup
- create / validate trader profile
- register signatory and seal information
- register production facilities
- capture eCoSys readiness and digital-signature readiness

### Phase 2. Case initiation
- create case
- choose target form family and filing mode
- choose shipment scope / export run

### Phase 3. Evidence ingestion
- ingest export declarations
- ingest import declarations
- ingest BOM / manufacturing process
- ingest domestic input evidence
- ingest cost/value data

### Phase 4. Normalization and mapping
- normalize codes
- normalize UOM
- validate required document presence
- build shipment and material identity keys

### Phase 5. Allocation and reconciliation
- match export demand to available source material history
- split and allocate partial quantities
- validate against prior consumption
- create forward allocation records
- create reverse / residual records

### Phase 6. Origin evaluation
- run selected origin rule
- produce a reviewable explanation of why the case passes or fails
- identify missing or contradictory evidence

### Phase 7. Output generation
- produce evidence sheet outputs
- render form artifacts
- assemble submission bundle

### Phase 8. Filing and issuance
- prepare eCoSys submission record
- track submission status
- record correction loops
- store issued result

### Phase 9. Archive and audit
- seal case version
- retain documents and evaluation record
- support later audit / trace lookup

## Design Constraints

### 1. Stateful history is required
The legacy workbook depends on prior allocations.
The system therefore cannot model each shipment as a fully isolated transaction.

### 2. Spreadsheet migration is not enough
The logic is distributed across:
- formulas
- macros
- hidden sheets
- long-lived ledgers

The solution must reconstruct business semantics, not just import sheet values.

### 3. Paper and electronic outputs both matter
Even if filing is electronic, paper forms still matter operationally for some form families.

### 4. Data quality is a core product problem
From [Data Exploration Report](./2026-04-15-data-exploration.md):
- filenames and folders are inconsistent
- archives are nested
- spreadsheets dominate
- customs declaration bundles are huge

The system must absorb dirty inputs and still produce reliable outputs.

### 5. Auditability is mandatory
The system must make it possible to answer:
- which import records supported this export case
- which quantities were consumed
- which rule was applied
- which documents were used
- what changed after correction or resubmission

## System Design Risks

### 1. Hidden legacy rules
Some rules may live only in VBA branches or hidden sheets.
The workbook appears to contain both legacy and upgraded paths.

### 2. Unknown source of truth path
`RunUpgrade` appears to be the maintained path, but that still needs confirmation from live operator usage.

### 3. Historical data dependency
Migration will be difficult if `Save` and `Tru lui` contain accumulated state that operators rely on.

### 4. Case-family variation
The extracted archives show multiple case families and mixed statuses.
The same engine may be reused with dossier-specific conventions that are not yet fully documented.

### 5. Regulatory drift
Knowledge base notes reflect current MoIT/eCoSys assumptions.
Legacy agency files may still encode pre-2025 or transitional practices.

## Open Questions Before Detailed Solution Design

### Business questions
- Which workbook path is actually used day to day: `RunUpgrade` or older `Run1/2/3` flows?
- Are `Save` and `Tru lui` global ledgers per company, per workbook copy, or per period?
- What is the exact business meaning of the grouping key created in `DM!K6`?
- Which form families are used most often in real cases?
- Which fields are manually edited by operators after the workbook computes them?

### Data questions
- What are the canonical schemas for `NK`, `XK`, `DM`, and the criteria sheets?
- Which columns in the large customs sheets are semantically required vs incidental?
- How are code mappings and UOM conversions governed outside the workbook today?

### Product questions
- Should the first system release target one form family or the general engine?
- Should filing to eCoSys be in scope initially, or should the first release stop at submission-ready bundle generation?
- How much historical ledger state must be migrated before operators can trust the system?

## Design Readiness Conclusion
The current evidence is sufficient to begin solution design at the domain and architecture level.

What is already sufficiently clear:
- the end-to-end CO compliance workflow
- the existence of a stateful allocation and rule engine
- the main workbook modules and sheet responsibilities
- the key legal constraints around authority, filing channel, timing, origin rules, and retention

What still requires targeted discovery before implementation:
- exact operator path through workbook macros
- canonical field-level semantics of the main sheets
- migration treatment for historical ledgers
- prioritization of form families and filing integration scope
