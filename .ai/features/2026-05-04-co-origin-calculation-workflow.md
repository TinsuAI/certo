# Feature: C/O Origin Calculation Workflow

## Scope
Clarify the current C/O flow from invoice/market/form selection into the origin calculation table, and identify what is missing before supporting direct/build-up value-content formulas.

This brief does not implement the legal PSR engine, Data Hub API changes, allocation ledger, or a new UI flow.

## Decisions
- Current CO dev flow starts with invoice and market. The market/form preview writes `co_form_type`, `agreement`, and `rule` into the saved case, while HS criteria preview is recalculated from invoice-matched BCCT export rows and the configured form index.
- The origin tab is currently a read-first calculation surface. It builds products from invoice matches, selected BOM rows, material catalog rows, and CO-stock rows derived from BCCT import data.
- The current numeric evaluator is build-down only: `LVC/RVC = (FOB - VNM) / FOB * 100`.
- BOM can be changed per finished product through `bom_product_version_overrides`; changing the dropdown submits the origin form and rebuilds the snapshot with the selected product BOM version.
- The app should not treat the current criteria preview as the final legal rule engine. It is a configurable PSR preview layer.

## Risks
- Direct/build-up RVC is not implemented. It appears in CPTPP legal/config text, but not in the evaluator or persisted rule model.
- Criteria strings such as `RVC 30/40/50 tùy công thức` do not encode formula mode, valuation basis, or the exact threshold to apply, so parsing a single numeric threshold from text is not durable.
- Origin status defaults to non-origin when unknown, which is conservative but can overstate VNM if material catalog or supplier-origin data is incomplete.
- CO stock is currently used as a source for material unit value, but there is not yet a durable allocation ledger that locks consumption and prevents double use.
- Direct/build-up would require reliable `VOM` inputs. The current data model has material origin status and material values, but not a dedicated originating-value ledger that distinguishes local originating value, cumulated originating value, indirect materials, packaging, and agreement-specific treatment.

## Open Questions
- For each form/agreement and HS rule, which formula mode should the operator choose or should the system choose: build-down, build-up, focused value, net cost, or CTC-only?
- For direct/build-up, should `VOM` include only materials marked originating, or also direct labor, direct overhead, local processing value, packaging, and indirect materials where the agreement allows?
- Which Data Hub contract will provide validated originating material/value evidence and supplier declarations, if CO cannot derive it safely from current material catalog and BCCT data?
- Should the origin tab become a mode-aware table that can switch between LVC/RVC build-down, RVC build-up, CTC, and compound rules, or should each rule family have a separate evidence table?
