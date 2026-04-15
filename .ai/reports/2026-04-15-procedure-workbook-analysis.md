# Procedure And Workbook Analysis

## Files Analyzed
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/QUY TRÌNH XIN CẤP CO.pdf`
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/Lưu trình xin CO.jpg`
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/tru lui CO final  SXXK - 2025 commercial-MAC - Huyền đúng.xlsm`

## Scope
Understand the operational CO procedure and the workbook logic behind it.

Out of scope:
- Rebuilding the workbook
- Validating every numeric output against live business cases
- Converting workbook logic into an application model

## Procedure From PDF And JPG

### 1. First-Time Registration
- The process starts with enterprise profile registration on ECOSYS / Ministry of Industry and Trade.
- Required onboarding inputs:
  - business registration certificate
  - seal and signature samples
  - list of production facilities
  - tax registration information
- The PDF states the first approval takes about `6-12` hours after registration.
- The JPG presents the same stage as `REGISTRATION OF ENTERPRISE PROFILE ON ECOSYS` and labels it as about `1 day`.

### 2. Case Preparation
- Once registered, the staff must determine the correct CO form for the market/agreement.
- Required dossier inputs from the PDF:
  - application form
  - CO form
  - export customs declaration
  - invoice
  - packing list
  - bill of lading
  - CTC / RVC / LVC criteria sheet
  - manufacturing process summary
  - import customs declarations when imported materials are used
  - domestic material purchase invoices or origin commitment
  - specialist confirmation for regulated details such as manufacturer name, production date, expiry, radioactive content

### 3. Electronic Form vs Paper Form
- The PDF explicitly splits the process into electronic CO forms and paper CO forms.
- Electronic forms listed in the PDF:
  - `D, E, AI, AJ, AK, AANZ, AHK, RCEP, S, VC, VJ, VK, VN-CU, CPTPP`
- Paper forms listed in the PDF:
  - `EUR1, EUR1 UK, B, X, T`
- The PDF says electronic forms only need documents uploaded to the system.
- The PDF says paper forms require `4` physical copies: `1` original and `3` copies.
- The JPG also implies different handling paths and includes a market-to-form matrix with examples such as `AI`, `EUR1`, `B`, `E`, `D`.

### 4. Decision Gates
- First-time applicant or not
- Electronic form or paper form
- Which trade agreement / market form applies
- Whether imported materials are involved
- Whether the manufacturing process is complex
- Whether `LVC > 30%`
- Whether HS code criteria are satisfied
- Whether specialist confirmation is required
- Whether on-site production verification is required

### 5. Turnaround Time
- The PDF states issuance should be within `3` working days after a valid dossier is submitted.
- If factory verification is needed, it can extend to `5` working days.
- The JPG adds practical timing hints:
  - paper form: around `1` working day
  - e-form: around `3` days for ordinary goods
  - e-form: around `7` days for electronics

### 6. Role Split
- Import/export department:
  - determine form type
  - prepare BOM / material norm
  - prepare import declarations and source documents
  - hand off dossier
  - archive approved CO
- Accounting:
  - build material norms
  - retain incoming invoices
- Trọng Tín:
  - receive dossier
  - advise for first-time applications
  - complete criteria sheets
  - complete application dossier
  - update electronic or paper CO
  - archive approved CO

### 7. Operational Meaning
- The procedure is not only document collection.
- It combines:
  - enterprise registration
  - dossier assembly
  - trade-agreement decisioning
  - origin-rule evaluation
  - manufacturing justification
  - audit retention

## Workbook Structure

### Visible Sheets
- `NK`
- `NK2`
- `XK`
- `DM`
- `Xuat`
- `X-N`
- `Save`
- `Tru lui`
- `Chiphi`
- `LVC`
- `RVC`
- `EUR1`
- `CTH`
- `CTSH`

### Hidden Sheets
- `WOIII`
- `FORM B`
- `FORM X`
- `PTN`

### Sheet Footprint
- `Save`: `A1:AA129726`, `0` formulas
- `Tru lui`: `A1:W129918`, `0` formulas
- `NK`: `A1:BB30877`, `1098` formulas
- `NK2`: `A1:Y30871`, `30871` formulas
- `DM`: `A1:AF27347`, `71` formulas
- `X-N`: `A1:Y13773`, `27` formulas
- `XK`: `A2:BB1164`, `435` formulas
- `Xuat`: `A1:Z2169`, `2` formulas
- `LVC`: `A1:JA1624`, `105` formulas
- `RVC`: `A1:JA1624`, `159` formulas
- `EUR1`: `A1:JA1624`, `159` formulas
- `CTH`: `A1:JA1624`, `161` formulas
- `CTSH`: `A1:JA1624`, `161` formulas
- `WOIII`: `A1:JA124`, `173` formulas
- `FORM B`: `A1:T103`, `104` formulas
- `FORM X`: `A1:T89`, `95` formulas
- `PTN`: `A1:T103`, `26` formulas

## Workbook Security And Control
- The workbook contains `xl/vbaProject.bin`; it is macro-driven.
- `Workbook_Open` is present in `ThisWorkbook`.
- The workbook checks machine MAC address via a security module.
- The code contains time-lock logic with cutoffs tied to `2025-12-31` and upgraded paths tied to `2026-12-31`.
- This means the file is intentionally controlled and likely used as an internal licensed tool rather than a generic spreadsheet.

## Workbook Modules Found
- `UndoTrudon`
- `CongdonXoabangke`
- `LocmaSapxepLaydata`
- `TachdongDeleteXN`
- `Save`
- `DM`
- `Trului`
- `HideCopy`
- `Run1`
- `Run2`
- `Run3`
- `RunUpgrade`
- `Inctu`
- `xuatCtu`
- `protect`
- `Security`
- plus `ThisWorkbook` and multiple sheet code modules

## Workbook Pipeline

### 1. Import Data Intake
- `NK` appears to be the raw import customs sheet.
- `NK2` is a processed / normalized layer derived from `NK`.
- Evidence:
  - module names `layDataNK`, `layDataNKArr`
  - `NK2` has very high formula density
  - workbook named ranges show filter areas on both `NK` and `NK2`

### 2. Export Data Intake
- `XK` is the export-side source.
- The certificate sheets repeatedly look up data from `XK`.
- Formula evidence:
  - `RVC!B9`, `EUR1!B9`, `CTH!B9`, `CTSH!B9`, `WOIII!B9` all read dates/details from `XK`
  - output sheets reference `XK` for incoterm, exchange rate, export value, and export declaration fields

### 3. Current Run Selector
- `DM` appears to be the selector for the current CO run or product grouping.
- Strong evidence:
  - module `DM.sumifDM`
  - VBA comments showing `DM!K6` is calculated from `XK`
  - that result is written into `NK2!V3` and `Xuat!B1`
- Inference:
  - `DM` is the sheet that decides which export batch / code / model is currently being processed.

### 4. Selection / Staging
- `Xuat` looks like a selectable export list fed from `DM`.
- `X-N` is the central staging sheet where export demand is matched to import stock and transformed into a consumable ledger.
- Evidence:
  - VBA names `copyXuat`, `HideRowsXuat`, `tachDongArr`
  - formulas in `X-N`:
    - `U1 VLOOKUP($S$1,XK!$B$11:$D$99983,2,0)`
    - `T1 SUM(T4:T1000)`
    - `V1 SUM(V4:V900000)`
  - subroutines explicitly split rows when stock and required quantity do not align

### 5. Historical Fact Table
- `Save` is the long-term fact table / audit table of already allocated consumption.
- Strong evidence:
  - huge sheet size, no formulas
  - VBA comments refer to writing output arrays into `Save`
  - code builds `Save!W = R & S` as a composite lookup key
- Inference:
  - each CO run adds rows into `Save`, and later certificate sheets query it to reconstruct provenance / prior allocations.

### 6. Reverse Ledger
- `Tru lui` is the reverse ledger / decrement ledger.
- Strong evidence:
  - module `Trului`
  - `truLuiArr`
  - strings such as `SL su dung cua Trului khop`
- Inference:
  - this sheet tracks deduction against available import quantities and probably supports rollback / reconciliation of usage history.

### 7. Cost Sheet
- `Chiphi` is a compact cost input / summary sheet.
- Inference:
  - it likely feeds labor / overhead / profit pieces that participate in LVC/RVC calculations.

### 8. Certificate Output Layer
- `LVC`, `RVC`, `CTH`, `CTSH`, `EUR1`, `WOIII` are output templates for different origin criteria or form families.
- Hidden `FORM B`, `FORM X`, `PTN` are additional output/support templates.
- Evidence:
  - print areas are defined on all these sheets
  - VBA has dedicated cleanup and generation subroutines:
    - `XoaLVC`
    - `XoaRVC`
    - `XoaCTH`
    - `XoaCTSH`
    - `runUpgradeLVC`
    - `runUpgradeRVC`
    - `runUpgradeCTH`
    - `runUpgradeCTSH`

## Core Logic In The Workbook

### Composite Keys
- `XK` and `Save` are linked by composite keys.
- Formula evidence:
  - `XK!Q11 = B11&T11&U11`
  - repeated shared formulas continue this pattern
- Inference:
  - the workbook creates a stable unique business key by concatenating declaration / sequence / material code style fields.

### Normalization And Aggregation
- `DM` uses formulas like:
  - `COUNTIF($A$7:A7,A7)&A7`
  - `SUM(...)`
- Inference:
  - `DM` normalizes repeated product keys and aggregates quantities / values per item or declaration group.

### Certificate Population
- Output templates inherit header values from `LVC` or `XK`.
- Formula evidence:
  - `RVC!B6 = LVC!B6`
  - `RVC!B7 = LVC!B7`
  - `EUR1!B6 = LVC!B6`
  - `PTN!L2 = 'FORM B'!K3`
  - `FORM B!Q9 = Xuat!B1`
  - `FORM X!Q10 = LVC!Q10`
- Inference:
  - `LVC` behaves like the base template/header source, and other criteria/forms reuse the same identity block and adapt the body/footers.

### Origin And Value Calculations
- VBA strings explicitly mention:
  - `Tinh LVC`
  - `RVC %`
  - `CTH %`
  - `CTSH %`
  - `lay xuat xu`
  - `ng xuat xu`
  - `ng tin RVC`
- There are repeated references to:
  - domestic value
  - non-origin value
  - FOB
  - costs
  - export value
- Inference:
  - the workbook computes origin ratios by combining export value with material allocation and cost components, then fills the appropriate proof sheet depending on the selected rule.

### Provenance Reconstruction
- A recurring pattern in `RVC/EUR1/CTH/CTSH/WOIII`:
  - `IF(LEFT(Q9,1)="3",Q9&" ngày : "&TEXT(VLOOKUP(...XK...),"dd/mm/yyyy"),...)`
- Inference:
  - the output sheets reconstruct declaration number plus declaration date based on export-side keys.
- VBA strings also reference concatenating multiple historical references from `Save`.
- This fits the requirement to show traceability from import declarations to export goods.

## Legacy Path vs Upgraded Path
- `Run1`, `Run2`, `Run3` exist alongside `RunUpgrade`.
- The VBA strings show `RunUpgrade` using `dictDM`, `dictSave`, `dictSave2`, `Collection`, and array-based processing.
- Inference:
  - `RunUpgrade` is a newer optimized implementation that replaced older repeated `VLOOKUP` / row-by-row logic with dictionary-based joins.
- This matters because the workbook likely contains both legacy and currently used logic.

## Printing And Export
- `Inctu` and `xuatCtu` handle printing / export.
- Strings show:
  - `Truong hop in tkn`
  - `CopyPages2`
  - `CopyPages3`
  - `xuatCtuPdf`
  - `CreateNewWb.SaveAs`
- Inference:
  - the workbook can build a new workbook containing selected TKN pages / certificate sheets and export them to PDF for dossier submission.

## Operational Interpretation
- This workbook is not a simple calculator.
- It is effectively a mini CO processing system with:
  - data import normalization
  - stock allocation
  - reverse deduction
  - historical audit persistence
  - rule-specific origin calculations
  - form generation
  - print/PDF packaging
- The real business workflow therefore has two layers:
  - document procedure in the PDF/JPG
  - allocation and origin engine in the `.xlsm`

## Key Risks For Future Productization
- Logic is split across:
  - worksheet formulas
  - hidden sheets
  - VBA modules
  - workbook state in `Save` and `Tru lui`
- The workbook is stateful. Reproducing outputs will require replaying ledger history, not only current-case inputs.
- Security/time-lock and MAC gating mean the file is not designed for clean multi-user deployment.
- `RunUpgrade` and `Run1/2/3` imply old and new logic coexist. A product rewrite must identify which path is the source of truth.

## Best Current Understanding
- Procedure side:
  - collect correct dossier
  - classify correct form
  - prove origin with criteria sheets and manufacturing data
  - submit to issuing authority
- Workbook side:
  - select export batch
  - map export demand to imported/domestic material history
  - calculate rule-specific origin eligibility
  - generate the required evidence sheets and printable forms
