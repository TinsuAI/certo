# CO Notes From V-Notes

## Provenance
Requested source:
- `C:\Users\sys\Dropbox\Obsidian\V-Notes\30_Resources`

Resolved from WSL:
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources`

Primary notes used:
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources/01_Wiki/Certificate-of-Origin.md`
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources/01_Wiki/eCoSys.md`
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources/01_Wiki/Origin-Rules.md`
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources/01_Wiki/Trong-Tin-Consulting.md`
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources/Media_Vault/Others/QUY-TRINH-XIN-CAP-CO-PDF.md`
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources/Media_Vault/Others/Luu-trinh-xin-CO-IMG.md`
- `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources/Media_Vault/Others/co-deep-research-report.md`

## High-Signal Facts

### 1. C/O authority in Vietnam
- As captured in the wiki notes dated `2026-04-14`, C/O issuance authority was centralized under the Ministry of Industry and Trade (`MoIT`) from `May 2025`.
- The notes say VCCI no longer issues C/O after that transfer.
- Implication for this project:
  - the product should model MoIT as the issuing authority, not VCCI
  - historical processes may still reference VCCI, so legacy documents may not match the current issuing flow

### 2. eCoSys is the mandatory filing channel
- The wiki says `eCoSys` is the centralized digital platform for filing, processing, status tracking, and issuance of C/O in Vietnam.
- It describes `ecosys.gov.vn / co.moit.gov.vn` as the platform endpoints.
- It also says:
  - first-time registration takes around `6-12 hours` or about `1 working day`
  - digital signature is required
  - issued C/Os can be downloaded as PDF
- Implication:
  - future workflow design should assume electronic filing is mandatory, even if paper forms still exist as outputs or submission artifacts

### 3. Core procedural timings
- The notes consolidate the timings found in the PDF/JPG:
  - enterprise profile registration: `6-12 hours`
  - standard valid application issuance: up to `3 working days`
  - on-site inspection case: up to `5 working days`
  - paper forms: typically `1 working day`
  - e-forms for general goods: about `3 days`
  - e-forms for electronic goods: about `7 days`
- Implication:
  - the system should track SLA expectations per form/type, not a single generic status timer

### 4. Origin rules that matter
- The wiki’s `Origin-Rules` note explicitly captures the criteria:
  - `WO`
  - `CTC`
  - `RVC`
  - `LVC`
- It also records formulas:
  - `RVC = (FOB – non-origin material value) / FOB × 100%`
  - `LVC = (FOB – CIF value of imported or undetermined-origin inputs) / FOB × 100%`
- It states imported materials are treated as non-originating in origin calculations, even when duty-exempt.
- Implication:
  - the workbook logic we saw around `LVC`, `RVC`, `CTH`, `CTSH`, `EUR1` matches the wiki’s regulatory summary
  - the future app must model imported inputs separately from domestic/originating inputs

### 5. Dossier checklist for first filing
Across the procedural notes and deep report, the required dossier includes:
- application form
- C/O form
- export customs declaration
- invoice
- packing list
- bill of lading or equivalent transport document
- origin declaration / criteria sheet
- supplier or manufacturer declaration for domestic inputs
- manufacturing process description
- BOM
- import declarations for imported inputs
- domestic purchase invoices / supporting proof

The deep report adds an important retention rule:
- origin and trade records should be kept for at least `5 years`

Implication:
- the product should distinguish:
  - per-shipment documents
  - reusable product/origin-supporting documents that remain valid across shipments for a limited period
  - long-term compliance archive

## Operational Insights From The V-Notes

### 1. Paper form vs e-form is not just presentation
- The notes treat paper forms and e-forms as operationally different lanes.
- Paper forms such as `EUR1`, `B`, `X`, `T` may still require printed copies and separate handling.
- The procedural image note explicitly mentions different timelines by form category.
- Implication:
  - a case should likely store both:
    - issuance channel
    - C/O form type

### 2. Trong Tin’s role is an outsourced compliance operator
- The wiki note for `Trong-Tin-Consulting` frames them as a specialist advisor/operator helping enterprises navigate eCoSys and regulatory requirements.
- It highlights division of labor between:
  - import-export
  - accounting
  - consultant/operator
- Implication:
  - the future system may need role-aware workflow, not just a single “staff user”

### 3. The product is closer to compliance operations than simple document management
- The legal/procedural notes, combined with the workbook, indicate the real problem is:
  - registering trader profile
  - collecting and validating supporting documents
  - proving origin under the correct rule
  - generating the right evidence sheet/form
  - keeping audit-proof records
- Implication:
  - a naive “upload docs and export a PDF” app would undershoot the actual problem

## Regulatory / Design Implications For Barry CO

### 1. Entities the product will probably need
- trader / company profile
- authorized signatory / seal sample
- production facility
- shipment
- export declaration
- import declaration
- supporting document
- BOM / manufacturing process record
- origin rule evaluation
- form type
- filing in eCoSys
- issued C/O
- retention / audit record

### 2. State transitions the product will probably need
- first-time profile registration
- profile approved
- dossier drafting
- evidence complete
- origin rule satisfied
- filed to eCoSys
- issued
- corrected / resubmitted
- archived for audit

### 3. Constraints the product should respect
- digital signature requirement
- filing through eCoSys
- different handling for paper vs electronic forms
- 5-year record retention
- imported inputs counted as non-originating
- SLA differences by form/type and inspection status

## What This Adds Beyond The Local Agency Files
- The local agency files showed the operational artifacts and workbook logic.
- The V-Notes add a cleaner layer of:
  - current issuing authority
  - filing platform
  - legal timing expectations
  - formal origin-rule framing
  - documentary retention requirements
- Together they confirm that the current workbook is implementing a real regulatory workflow, not just a custom office spreadsheet.
