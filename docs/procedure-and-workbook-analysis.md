# Procedure And Workbook Analysis

## Files Analyzed
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/QUY TRÌNH XIN CẤP CO.pdf`
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/Lưu trình xin CO.jpg`
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/tru lui CO final  SXXK - 2025 commercial-MAC - Huyền đúng.xlsm`

## Procedure Layer

### First-time registration
The process begins with enterprise registration on eCoSys.

Required onboarding inputs:
- business registration certificate
- seal sample
- authorized signature sample
- production facility list
- tax registration information

### Shipment filing
After registration, each shipment requires a specific C/O dossier.

Typical dossier contents:
- C/O request form
- C/O form
- export customs declaration
- invoice
- packing list
- bill of lading
- criteria sheet for `CTC` / `RVC` / `LVC`
- manufacturing process summary
- import declaration evidence if imported inputs are used
- domestic material evidence or origin commitment

### Product reuse behavior
This procedure should be read as:
- trader profile is registered once
- each shipment needs its own filing
- product-origin evidence for the same fixed product may be reused for later shipments within its validity window, unless facts change

### Operational split
- Import-export team prepares the shipment-side dossier
- Accounting prepares BOM / material evidence and source invoices
- Trọng Tín or equivalent compliance operator finalizes the criteria sheets and filing package

## Workbook Layer

### Visible sheets
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

### Hidden sheets
- `WOIII`
- `FORM B`
- `FORM X`
- `PTN`

### What the workbook is doing
The workbook is acting as a rule engine and ledger system that:
- normalizes import and export data
- chooses the current export run
- allocates export demand against import/material history
- writes historical consumption into `Save`
- writes reverse / decrement information into `Tru lui`
- generates criteria sheets and output forms

### Workbook pipeline
1. `NK -> NK2`
   Import-side normalization
2. `XK`
   Export-side source
3. `DM -> Xuat`
   Select the current run / grouping
4. `X-N`
   Match export demand to import/material history
5. `Save`
   Persist historical usage
6. `Tru lui`
   Reverse / carry-forward / reconciliation ledger
7. `LVC/RVC/CTH/CTSH/EUR1/...`
   Generate rule-specific evidence and output sheets

### Core workbook modules found
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

### Operational meaning
This workbook is not a one-off calculator.
It stores state and historical usage, so the current shipment depends on prior allocations.

That means the future system will need:
- forward allocation records
- reverse / adjustment records
- rule evaluation outputs
- archive / audit persistence
