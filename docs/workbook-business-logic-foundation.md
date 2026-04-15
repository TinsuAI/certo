# Workbook Business Logic Foundation

## Purpose
This document describes the business logic needed to design a software system that can replace or absorb the current Excel-based CO process.

Detailed supporting materials:
- [Procedure And Workbook Analysis](./procedure-and-workbook-analysis.md)
- [CO Knowledge Base](./co-knowledge-base.md)
- [Data Exploration](./data-exploration.md)
- [Origin Qualification Case Studies](./origin-qualification-case-studies.md)

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

### Direct VBA-confirmed operational behavior
- `Workbook_Open` enforces a MAC-address allowlist and closes the workbook on mismatch
- `protect` / `unProtected` unlock and re-lock the main working sheets with a hardcoded sheet password
- `DM.sumifDM` computes the current run key in `DM!K6`, then pushes it into `NK2!V3` and `Xuat!B1`
- `HideCopy.copyXuat` copies selected export-demand rows from `Xuat` into `X-N`, then writes a `CountIf` marker back into `NK2`
- `LocmaSapxepLaydata.layDataNKArr` normalizes `NK` into `NK2` by header mapping, while `locMaArr` filters qualified `NK2` rows into `X-N`
- `AtoZArr` sorts `X-N` by material code and computes comparison totals in column `U`
- `TachdongDeleteXN.tachDong2` / `tachDongArr` split rows when one demand row must consume multiple source rows, then compute actual used quantity in column `V`
- `Save.saveArr` appends rows with `V > 0` from `X-N` into `Save`, builds the helper key `W = R & S`, and immediately calls `truLuiArr`
- `Trului.truLuiArr` writes the reverse / residual ledger, backfills initial source quantity from `NK`, and flags duplicate / zero-stock cases
- `CongdonXoabangke.CongDonArr` adds used quantity back into `NK2.Q`, clears `X-N`, and resets the working `DM` range
- `RunUpgrade` is the current multi-form generator for `LVC`, `RVC`, `CTH`, `CTSH`, and `EUR1`
- `xuatCtu` and `inCtu` assemble or print supporting customs / PDF documents from external source files referenced by the workbook

## Business Capabilities The System Must Support

### 1. Registration and profile management
- maintain enterprise profile
- maintain signatory / seal / production facility data
- track eCoSys readiness

### 2. Shipment dossier management
- create shipment case
- collect shipment-specific docs
- track missing docs
- tie shipment to the target C/O form type and applicable agreement

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

Confirmed workbook finding from direct sheet inspection:
- CO-available stock is tracked per import-source row, not only per aggregated material code
- the effective granularity is at least `import declaration number + import line number + material code`
- `NK2` exposes import-side source rows with fields such as `Số TK`, `STT hàng`, `Mã NPL/SP`, `Tổng số lượng`, `Đã xuất`, and `Tồn`
- `Save` stores forward allocation records that link one export run `TKX` to one import-source row and the quantity consumed from that row
- `Tru lui` stores the reverse / residual view of the same source rows with columns for `Số lượng đã xuất`, `Số lượng còn lại`, `Số lượng xuất đợt này`, and `Số lượng còn lại cho đợt sau`
- this means one material can have multiple separate CO stock buckets if it appears across multiple import declarations or import lines
- allocation therefore preserves provenance at source-row level and deducts each bucket independently

Design implication:
- the workbook is modeling a CO eligibility ledger, not a full physical-inventory system
- its `Tồn` fields should be interpreted as remaining CO-available quantity within the origin/allocation model
- future system design should keep `CO stock` and `physical inventory` as separate concepts, with optional reconciliation between them rather than a single shared balance
- the future system will need an explicit run key / allocation batch concept equivalent to `DM!K6`
- export-demand selection and source-row qualification are distinct steps and should not be collapsed into one opaque transform

### 5. Origin rule engine
- support `WO`, `CTC`, `RVC`, `LVC`
- support observed case rules such as `CTH`, `CTSH`, `CC`, `PSR`
- support compound rules such as `RVC 35% + CTSH`
- support rule-specific outputs and evidence sheets
- make pass/fail and supporting explanation reviewable

Confirmed case-study finding from completed dossiers:
- Vietnam-origin qualification in practice is rule-based, not purity-based
- completed dossiers contain many `Không xuất xứ` input rows and still conclude pass under the applicable rule
- the same business or product family can qualify under different rule families in different filings

Design implication:
- the future system needs a configurable multi-rule origin engine
- origin evaluation must be driven by `applicable agreement + product case`, not by one global formula
- the chosen `C/O form type` should be stored separately in the filing / issuance layer
- explainability is mandatory because operators must defend why a shipment passed even when some inputs are non-originating

### 6. Filing and issuance tracking
- prepare eCoSys-ready case
- track submission, correction, issuance, and inspection
- store issued result and archive

### 7. Auditability
- retain evidence for at least the compliance retention period
- reconstruct how each issued shipment was supported
- trace import/source records used in each origin evaluation

### Direct VBA risks and migration constraints
- access to the workbook is gated by MAC-address checks at startup, so operational behavior is tied to specific machines
- the working sheets use a hardcoded protection password, so business logic and editability are partially coupled
- `Run1` / `Run2` / `Run3` still coexist with `RunUpgrade`, which suggests the workbook contains both legacy and newer generation paths
- several macros contain hardcoded expiry dates that force-close the workbook after a deadline
- document export / print logic depends on local filesystem paths stored in workbook cells such as `Save!X1` and `Save!Y1`
- many routines rely on `ActiveWorkbook`, `ActiveSheet`, selected sheets, and fixed row/column coordinates, which makes the behavior environment-sensitive
- some legacy routines still use brittle row-bound logic such as `CurrentRegion.Rows.Count` as if it were an absolute last-row index; the array-based `*Arr` variants appear safer and more maintainable

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
- COFormType
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
- Which C/O form types should be covered in the first system release?
- How much historical state must be migrated before operators trust the new system?
