# Origin Qualification Case Studies

## Purpose
This document records concrete completed-dossier examples that show how goods are being qualified as Vietnam-originating in practice.

The purpose is not to restate legal theory.
The purpose is to capture the actual rule patterns seen in completed cases so the future system can model them explicitly.

Related documents:
- [Business Logic Foundation](./workbook-business-logic-foundation.md)
- [CO Knowledge Base](./co-knowledge-base.md)
- [Procedure And Workbook Analysis](./procedure-and-workbook-analysis.md)

## Core Finding
The completed dossiers do support Vietnam-origin treatment, but not because all inputs are domestic or wholly obtained.

The observed pattern is:
- the goods are manufactured in Vietnam
- the dossier identifies imported or otherwise non-originating inputs
- the dossier then proves that the finished goods satisfy the applicable origin rule under the target agreement

In other words:
- `Vietnam origin` in these dossiers means `originating under the applicable rule`
- it does not mean `all materials are from Vietnam`

## Case Study 1. Growatt Inverters

### Files
- [Bang RVC GIN01425L031.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/6. Bang RVC GIN01425L031.xlsx)
- [QUY TRINH SAN XUAT MÁY BIẾN TẦN.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/5.  QUY TRINH SAN XUAT MÁY BIẾN TẦN.pdf)

### Observed rule pattern
- The workbook-derived evidence sheets use `RVC 35% + CTSH`.
- The same shipment contains multiple product models, each with its own evidence sheet and calculated result.

### Evidence
- Every product sheet in the workbook states `Tiêu chí áp dụng: RVC 35% + CTSH`.
- Example product outcomes:

	- `PV00.0048500`: `Kết luận: Sản phẩm đạt tiêu chí RVC 35.88% + CTSH`
	- `PV01.0117600`: `Kết luận: Sản phẩm đạt tiêu chí RVC 40.19% + CTSH`
	- other model sheets also conclude with values above the threshold

- The same sheets list many input rows marked `Không xuất xứ`.

### What this means
- The product is not being qualified as wholly obtained.
- The dossier accepts that some inputs are non-originating.
- Qualification comes from a combined rule:

	- value-content threshold
	- tariff-subheading change condition

### Calculation pattern seen in the evidence sheet
- The RVC sheet shows the indirect formula pattern:

	- `RVC = (FOB - CIF value of non-originating inputs) / FOB x 100`

- The sheet then compares the calculated result to the required threshold and records a pass conclusion.

### Business implication
- The future system must support:
  - product-level RVC calculation
  - linkage to non-origin input value
  - simultaneous use of a tariff-change condition such as `CTSH`
  - per-model evaluation within one shipment

## Case Study 2. Do Thanh Aluminum Frame

### Files
- [PHỤ LỤC V NHÔM KHUNG INGOT SL01.HLN 156HC.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/6. PHỤ LỤC V NHÔM KHUNG INGOT SL01.HLN 156HC.xlsx)
- [Quy trình sản xuất nhôm solar xuất khẩu nhập Ingot.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH/5. Quy trình sản xuất nhôm solar xuất khẩu nhập Ingot.pdf)

### Observed rule pattern
- The evidence sheet states `Tiêu chí áp dụng: CTSH`.
- The conclusion states `Hàng hóa đáp ứng tiêu chí “CTSH”`.

### Evidence
- The finished product is aluminum frame for solar modules with HS `854190`.
- The input table shows mixed origin:

	- a major aluminum billet input marked `Việt Nam`
	- multiple chemical/process inputs marked `Không xuất xứ`

### What this means
- The dossier is not relying on all inputs being domestic.
- It is relying on the product meeting the required tariff-shift rule after manufacturing in Vietnam.

### Business implication
- The future system must support:
  - tariff-shift evaluation without requiring a value-content calculation
  - mixed-origin inputs within one evidence set
  - explicit proof that the manufacturing process in Vietnam is substantive enough for the rule

## Case Study 3. Hong An Shoes, November 2025

### Files
- [PHU LUC V - TIEU CHI CTH HÀNG XUẤT ZARA (1).pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20251103 HONG AN/CTU XIN CO HAWH-20251103 HONG AN/5. PHU LUC V - TIEU CHI CTH HÀNG XUẤT ZARA (1).pdf)

### Observed rule pattern
- The file states `Tiêu chí áp dụng: CTH`.
- The conclusion states `Hàng hóa đáp ứng tiêu chí CTH`.

### Evidence
- The finished good is sports footwear under HS `640219`.
- The input table contains many inputs marked `Không xuất xứ`.
- Even so, the conclusion is positive.

### What this means
- The rule is not based on domestic-input purity.
- The rule is based on heading change between the finished good and non-originating inputs.

### Business implication
- The future system must be able to:
  - store origin rule by agreement and product
  - compare finished-good HS against non-origin input HS at the required tariff level
  - explain the pass/fail result in a way operators can review

## Case Study 4. Hong An Shoes, December 2025

### Files
- [TIEU CHI CC HÀNG XUẤT ZARA.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20251230 HONG AN/CTU XIN CO HAWH-20251230 HONG AN/3. TIEU CHI CC HÀNG XUẤT ZARA.pdf)

### Observed rule pattern
- The file states `Tiêu chí áp dụng: CC`.
- The conclusion states `Hàng hóa đáp ứng tiêu chí CC`.

### What this means
- The same business and product family can be qualified under a different rule in a different filing context.
- The target system cannot assume one company or one product line maps to one permanent formula.

### Business implication
- The rule engine must be aware of the applicable agreement and separate that from the chosen C/O form type.
- It must allow one product family to be evaluated under different origin rules depending on the case.

## Case Study 5. Hong An Shoes, EUR.1 / January 2026

### Files
- [TIEU CHI PSR HÀNG XUẤT ZARA.pdf](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/3. TIEU CHI PSR HÀNG XUẤT ZARA.pdf)
- [Mẫu In phôi CO EUR1 - 3805 ĐÔI.xlsx](/home/vp/workspace/client/barry-CO/data/extracted/CO/Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN/CTU XIN CO HAWH-20260108 HONG AN/Chứng từ in bản giấy/Mẫu In phôi CO EUR1 - 3805 ĐÔI.xlsx)

### Observed rule pattern
- The evidence file states `Tiêu chí áp dụng: PSR`.
- The conclusion states:

	- `Hàng hóa đáp ứng tiêu chí PSR, sử dụng bất kì nguyên liệu từ nhóm nào để sản xuất sản phẩm ngoại trừ nhóm của sản phẩm.`

### Evidence
- The finished footwear shipment is paired with a file used to prepare the paper EUR.1 output, placing `VIETNAM` as the origin/exporting country for a Spain-bound case.
- The input table still contains non-originating materials.

### What this means
- The dossier is applying a product-specific rule rather than a generic one-rule-for-all approach.
- The target system must be able to evaluate and explain PSR-style logic, not only RVC or generic CTC.

## Cross-Case Patterns

### 1. Vietnam origin is rule-based
Across the completed dossiers, `Vietnam origin` means:
- the final goods are produced in Vietnam
- the applicable FTA rule is satisfied

It does not mean:
- all inputs are from Vietnam
- all inputs are already originating

### 2. Non-origin inputs are normal
Completed dossiers repeatedly show:
- imported or non-originating materials
- explicit customs or invoice references for those materials
- successful qualification anyway

The system must therefore model non-originating inputs as a normal case, not an exception.

### 3. Rule families vary by case
Observed rule families in the completed data:
- `RVC 35% + CTSH`
- `CTH`
- `CTSH`
- `CC`
- `PSR`

This is enough evidence to say the target system needs a multi-rule engine.

### 4. Manufacturing process evidence matters
Several dossiers include manufacturing-process documents.
That matters because tariff-shift or PSR qualification depends on substantial transformation in Vietnam, not just document packaging.

## Design Requirements For The Future System

### Required rule-engine behavior
The system must be able to:
- evaluate different rule families on the same platform
- choose rule logic by agreement and product case
- support compound rules such as `RVC + CTSH`
- support product-specific rules such as `PSR`
- explain pass/fail reasoning in a reviewable way

### Required data behavior
The system must be able to:
- link the finished-good HS code to product metadata
- link each input to origin status, source documents, HS code, and cost/value
- reuse BOM and source history across shipments while preserving shipment-specific evaluation
- retain the exact evidence used for each issued case

### Architectural implication
This should be implemented as a configurable origin-rule engine, not as a single hardcoded formula set.
At minimum, the engine needs:
- rule family selection
- rule parameterization
- evaluators for tariff-shift and value-content logic
- support for compound rule combinations
- explainable outputs for operator review and authority response
