# CO Input/Output Model

## Purpose
This document makes the CO dossier process explicit in terms of:
- required inputs
- produced outputs
- where those inputs and outputs appear in the real case data
- which procedural or legal requirements support them

This is a design document for the future system.
It is not only a process summary.

Legal and procedural sources in this document were re-checked on `2026-04-15`.

Related documents:
- [CO Knowledge Base](./co-knowledge-base.md)
- [Workbook Business Logic Foundation](./workbook-business-logic-foundation.md)
- [Origin Qualification Case Studies](./origin-qualification-case-studies.md)
- [Procedure And Workbook Analysis](./procedure-and-workbook-analysis.md)

## Executive Model
The CO process has three different input/output layers that should not be merged:

1. `Trader profile registration`

	Company-level eligibility to file.

2. `Product-origin evidence`

	Product-level proof package showing why a product can qualify under a specific origin rule.

3. `Shipment-level CO filing`

	Shipment-level application package tied to one export shipment and one target C/O form type.

There is also a fourth internal layer:

4. `Origin evaluation and allocation`

	The rule and traceability engine that turns source material history and product evidence into a pass/fail origin result and a reviewable evidence sheet.

## Layer 1. Trader Profile Registration

### Purpose
Establish the company as an eligible filer on the issuing platform before any shipment filing.

### Inputs
- company identity
- enterprise registration certificate
- tax registration details
- authorized signatory sample
- company seal sample
- production facility list

### Legal support
- `Nghị định 31/2018/NĐ-CP`, Article 13:

	- first-time applicants must register trader profile before C/O can be considered
	- profile includes signature sample, enterprise registration copy, and production-facility list

- the same article also states:

	- profile can be declared through `www.ecosys.gov.vn`
	- changes must be updated before filing
	- the profile must still be refreshed every `2 years` if unchanged

### Outputs
- valid trader profile on eCoSys
- approved signatory/seal reference
- registered production-facility list
- organizational readiness to file shipment cases

### Real-case evidence
- the clearest visible completed-case example is:

	- [DonDeNghi_EUR_df4abbb1-ad58-4429-56a7-08de52b08360.docx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/DonDeNghi_EUR_df4abbb1-ad58-4429-56a7-08de52b08360.docx)

- this application artifact explicitly states that the trader profile had already been registered and also exposes:

	- exporter identity
	- tax code
	- filing authority
	- shipment summary fields later reused in the filing

### Why this matters in system design
This is not shipment data.
It is reusable company master data with compliance status.

## Layer 2. Product-Origin Evidence

### Purpose
Create the reusable product-level evidence set that proves why a product can qualify under an origin rule.

### Inputs
- product identity
- model / SKU / product family
- finished-good HS code
- BOM or material norm
- manufacturing process
- source-material evidence:

	- import declarations
	- domestic VAT invoices
	- supplier or manufacturer declarations
	- import preference C/O when relevant

- cost/value evidence when the rule needs value-content calculation
- target rule or target agreement context:

	- `RVC`
	- `CTH`
	- `CTSH`
	- `CC`
	- `PSR`
	- compound rules such as `RVC 35% + CTSH`

### Legal support
- `Nghị định 31/2018/NĐ-CP`, Article 15:

	- for first-time product or new product filings, the dossier includes:

		- application
		- corresponding C/O form
		- export declaration
		- commercial invoice
		- transport document
		- criteria sheet
		- manufacturer/supplier origin declaration where applicable
		- manufacturing process copy
		- and, if needed, import declarations, domestic purchase invoices, export license, and other supporting documents

- the same article states that for fixed products:

	- only core shipment documents are required on later filings
	- criteria sheet, supplier/manufacturer declaration, and manufacturing-process documents remain valid for `2 years` unless changed

### Outputs
- rule-specific evidence set for a product or product family
- reusable evidence version for later shipments of the same stable product
- reviewable origin basis for the product

### Real-case examples

#### Growatt inverter case
Files:
- [Bang RVC GIN01425L031.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/6. Bang RVC GIN01425L031.xlsx)
- [QUY TRINH SAN XUAT MÁY BIẾN TẦN.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/5.  QUY TRINH SAN XUAT MÁY BIẾN TẦN.pdf)

Observed evidence inputs:
- product model
- finished-good HS
- shipment quantity and FOB
- detailed input-material table
- origin status per input
- import declaration references
- manufacturing process narrative

Observed evidence output:
- per-model origin conclusion such as `RVC 35.88% + CTSH`

#### Do Thanh aluminum frame case
Files:
- [PHỤ LỤC V NHÔM KHUNG INGOT SL01.HLN 156HC.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/6. PHỤ LỤC V NHÔM KHUNG INGOT SL01.HLN 156HC.xlsx)
- [Quy trình sản xuất nhôm solar xuất khẩu nhập Ingot.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/5. Quy trình sản xuất nhôm solar xuất khẩu nhập Ingot.pdf)

Observed evidence inputs:
- finished-good HS `854190`
- ingredient list with mixed origin
- Vietnamese billet source
- non-origin chemicals/process materials
- manufacturing-process support

Observed evidence output:
- explicit conclusion `Hàng hóa đáp ứng tiêu chí CTSH`

#### Hong An footwear case
Files:
- [PHU LUC V - TIEU CHI CTH HÀNG XUẤT ZARA (1).pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20251103 HONG AN/CTU XIN CO HAWH-20251103 HONG AN/5. PHU LUC V - TIEU CHI CTH HÀNG XUẤT ZARA (1).pdf)
- [TIEU CHI CC HÀNG XUẤT ZARA.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20251230 HONG AN/CTU XIN CO HAWH-20251230 HONG AN/3. TIEU CHI CC HÀNG XUẤT ZARA.pdf)
- [TIEU CHI PSR HÀNG XUẤT ZARA.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/3. TIEU CHI PSR HÀNG XUẤT ZARA.pdf)

Observed evidence inputs:
- same broad product family
- different shipment contexts
- different applicable rules
- imported or non-originating materials listed explicitly

Observed evidence outputs:
- one case passes `CTH`
- one case passes `CC`
- one case passes `PSR`

### Why this matters in system design
This layer is not just file storage.
It is versioned product-evidence logic with rule context.

## Layer 3. Shipment-Level CO Filing

### Purpose
Create the filing package for one export shipment.

### Inputs
- export declaration
- shipment quantity
- invoice
- packing list
- bill of lading or equivalent transport document
- destination market
- issuance channel
- applicable agreement
- target C/O form type
- references to product-origin evidence
- references to source-material allocation if required for proof

### Legal support
- `Nghị định 31/2018/NĐ-CP`, Article 15:

	- shipment-level dossier includes:

		- C/O application
		- corresponding C/O form
		- export declaration
		- commercial invoice
		- transport document
		- criteria sheet
		- and supporting origin evidence when applicable

- Article 16 and eCoSys FAQ:

	- filing can be electronic through `eCoSys`
	- in many cases the trader no longer needs to submit the paper dossier after submitting the electronic dossier
	- the issuing body returns an electronic approval and the trader prints the electronic C/O in color

### Outputs
- one filed CO case for one shipment
- electronic filing package and status on eCoSys
- C/O artifact appropriate to the issuance channel and target C/O form type

### Real-case examples

#### Growatt shipment case
Files under [DINH ECOSYS L031](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031):
- [1. TKX.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/1. TKX.pdf)
- [2. BL.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/2. BL.pdf)
- [7. INV + PBO.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/7. INV + PBO.pdf)
- [6. Bang RVC GIN01425L031.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/6. Bang RVC GIN01425L031.xlsx)

Shipment input pattern visible in the case:
- export declaration
- bill of lading
- invoice / packing evidence
- RVC evidence sheet
- manufacturing process

#### Do Thanh shipment case
Files:
- [1. ToKhaiHQ7X_QDTQ_308132641520.xls](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/1. ToKhaiHQ7X_QDTQ_308132641520.xls)
- [2. BL_SE202601010 SL01.HLN 156HC.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/2. BL_SE202601010 SL01.HLN 156HC.pdf)
- [7. Y26-MQDT-SL01.HLN 156HC - INV.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/7. Y26-MQDT-SL01.HLN 156HC - INV.pdf)
- [6. PHỤ LỤC V NHÔM KHUNG INGOT SL01.HLN 156HC.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/6. PHỤ LỤC V NHÔM KHUNG INGOT SL01.HLN 156HC.xlsx)

Shipment input pattern visible in the case:
- export declaration
- bill of lading
- invoice
- process document
- criteria appendix

#### Hong An EUR.1 shipment case
Files:
- [1. ToKhaiHQ7X_QDTQ_308133640200.xls](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/1. ToKhaiHQ7X_QDTQ_308133640200.xls)
- [6. INV - 363 CTNS - 3805 PRS - LCL - SEA (1).pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/6. INV - 363 CTNS - 3805 PRS - LCL - SEA (1).pdf)
- [7. PKL - 363 CTNS - 3805 PRS - LCL - SEA (1).pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/7. PKL - 363 CTNS - 3805 PRS - LCL - SEA (1).pdf)
- [3. TIEU CHI PSR HÀNG XUẤT ZARA.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/3. TIEU CHI PSR HÀNG XUẤT ZARA.pdf)
- [Mẫu In phôi CO EUR1 - 3805 ĐÔI.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/Mẫu In phôi CO EUR1 - 3805 ĐÔI.xlsx)

Shipment input pattern visible in the case:
- export declaration
- invoice
- packing list
- product-specific rule sheet
- file chuẩn bị mẫu C/O EUR.1 bản giấy
- application form containing the filing summary fields

### Why this matters in system design
This layer is shipment-scoped and tied to a specific C/O form type.
It should always be created per shipment even when product evidence is reusable.

## Layer 4. Origin Evaluation And Allocation

### Purpose
Turn shipment input plus product evidence plus source history into a defendable pass/fail origin result.

### Inputs
- shipment scope
- product code / model
- finished-good HS
- BOM / norm
- source-material history
- source-material origin status
- source-material value and quantity
- export FOB / shipment value
- selected rule family
- selected agreement

### Additional internal input from the workbook model
- allocation records from source rows in customs/invoice history
- reverse ledger / remaining CO-eligible balances
- prior usage history to prevent double consumption

### Outputs
- rule result:
  - pass or fail
  - rule family used
  - calculated percentage if relevant
  - tariff-shift result if relevant
- evidence sheet:
  - RVC sheet
  - CTH sheet
  - CTSH sheet
  - CC sheet
  - PSR sheet
- allocation trace:
  - which source inputs supported the shipment
  - how much was consumed

### Real-case examples
- Growatt output is a per-model RVC sheet with an explicit calculated result such as `35.88% + CTSH`
- Do Thanh output is a criteria appendix concluding `CTSH`
- Hong An output varies by case and agreement context:
  - `CTH`
  - `CC`
  - `PSR`

### Why this matters in system design
The system must not treat origin proof as a static upload.
It must support a configurable evaluation engine and explainable output.

## Final Issuance Outputs

### Possible outputs
- electronic approval on eCoSys
- printable electronic C/O PDF with QR
- paper-form output to accompany shipment
- signed exporter declaration where required
- archived dossier for later verification

### Legal support
- eCoSys FAQ states:
  - after electronic filing, the trader generally does not need to submit the paper dossier
  - the issuing body grants electronic approval
  - the trader prints the electronic C/O in color from PDF
  - the trader signs, prints name, and stamps the exporter declaration section if required by the agreement
- the current Ministry of Industry and Trade guidance also confirms that some forms are fully electronic while forms such as `EUR.1` still require paper originals for the importer side until the importing side formally accepts fully electronic exchange

### Real-case examples
- Hong An keeps both `Chứng từ khai điện tử CO` and `Chứng từ in bản giấy`, showing the same shipment can have both digital filing artifacts and paper-facing output artifacts
- Hong An also keeps [Mẫu In phôi CO EUR1 - 3805 ĐÔI.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/Mẫu In phôi CO EUR1 - 3805 ĐÔI.xlsx), which is a direct example of preparing a paper C/O output
- the same Hong An case also keeps the draft filing application [DonDeNghi_EUR_df4abbb1-ad58-4429-56a7-08de52b08360.docx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/DonDeNghi_EUR_df4abbb1-ad58-4429-56a7-08de52b08360.docx), showing the structured filing output before issuance
- Growatt keeps large assembled bundle PDFs:
  - [1-260.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/1-260.pdf)
  - [261-520.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/261-520.pdf)
  - [521-het.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/521-het.pdf)
  which look like compiled dossier-output artifacts for archive or submission handling

## Retention And Audit Output

### Legal support
- `Nghị định 31/2018/NĐ-CP`, Article 30:
  - issuing bodies must keep dossier records for at least `5 years`
  - traders requesting C/O must keep dossier records and related evidence for at least `5 years`

### Required outputs for the future system
- permanent dossier archive
- issue history
- evidence history
- allocation trace history
- ability to reproduce why a shipment passed origin review

## System Design Implications

### The future system must model distinct input domains
- company master data
- reusable product-origin evidence
- shipment filing data
- internal allocation and origin-evaluation data

### The future system must model distinct output domains
- compliance registration outputs
- evidence outputs
- filing outputs
- issuance outputs
- archive and audit outputs

### The future system must not flatten everything into one “document bundle”
That approach would lose:
- reuse boundaries
- validity windows
- shipment scope
- explainability of origin decisions
- audit traceability

## External Legal And Procedural References
- Nghị định 31/2018/NĐ-CP, full text on VBPL:
  - https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=128977
- Quyết định 2736/QĐ-BCT procedure listing on Thư Viện Pháp Luật:
  - https://thuvienphapluat.vn/van-ban/Xuat-nhap-khau/Quyet-dinh-2736-QD-BCT-2022-cong-bo-thu-tuc-hanh-chinh-linh-vuc-xuat-nhap-khau-547849.aspx
- eCoSys FAQ:
  - https://ecosys.gov.vn/Homepage/FAQ.aspx
- Ministry of Industry and Trade article on current C/O decentralization and electronic/paper practice:
  - https://moit.gov.vn/tin-tuc/thi-truong-nuoc-ngoai/dua-giay-khai-sinh-hang-hoa-ve-dia-phuong-cu-hich-cho-doanh-nghiep-xuat-khau.html
