# Feature: Multi-lot C/O stock allocation for origin statement

## Scope
- Allocate each BOM material requirement against one or more eligible C/O stock rows until the required quantity is covered.
- Keep the web `Xuất xứ` snapshot as the calculation source of truth; Excel `bảng kê` should export the accepted snapshot, including allocation trace lines.
- Preserve current one-material-row presentation for scanning, but add expandable/source details showing the individual stock rows used.
- Compute material value and VNM from allocated quantities per lot, not from a single best stock row.
- Do not mutate Data Hub or invent new `/v1/hub/*` calls from CO in the first phase.
- Do not solve global stock reservation across multiple C/O dossiers in the first phase unless a Data Hub or app-owned allocation ledger is approved.

## Current Behavior
- `app/main.py::co_stock_index()` builds a single-row lookup by `material_code`, `allocation_code`, and `customs_item_code`.
- `app/main.py::origin_material_from_bom_row()` reads only `stock_index[material_code]`.
- The selected stock row is ranked by active status, positive remaining quantity, and value availability, but quantity coverage is not checked.
- `used_qty` from `app/source_store.py::co_stock_rows_from_bcct()` is always `0`; `remaining_qty` currently mirrors import quantity for usable rows.
- UI, hidden form round-trips, workbook input/output, and dossier export mostly assume `1 material row = 1 source row`.

## Decisions
- Add an allocation layer between BOM material rows and origin material rows:
  - input: required material quantity, material code, stock candidates, valuation fallback data
  - output: `allocation_lines` plus summary fields kept for backward compatibility
- Match candidates using the same key family as today: BOM `material_code` against stock `material_code`, `allocation_code`, and `customs_item_code`.
- Sort candidates deterministically:
  - active/resolved rows first
  - positive `remaining_qty`
  - rows with usable value first
  - then declaration/line/source row for stable snapshots
- Allocate greedily until required quantity is met:
  - `allocated_qty = min(remaining_qty, remaining_required)`
  - if remaining required is still positive, mark shortage and keep partial result visible with warning
- Calculate values per allocation line:
  - `line_material_value = allocated_qty * unit_value`
  - `material_value = sum(line_material_value)`
  - if the material is non-origin, `non_origin_cif_value = material_value`
  - if unit prices differ, show a weighted/derived unit value or `Nhiều đơn giá`, while preserving each lot value in details
- Store allocation trace in the product snapshot:
  - `allocation_lines`: source row, declaration, line, available/remaining qty, allocated qty, unit value, currency, value source, value, origin/source metadata
  - summary fields such as `source_row`, `import_declaration_no`, `available_qty`, `unit_value`, `material_value`, `non_origin_cif_value` remain populated for existing UI/export paths.
- Treat phase-one allocation as a dossier snapshot only; it should not decrement shared stock.

## Risks
- Current `aggregate_by_declaration_and_allocation_code` can combine source rows and recompute unit value. That may be fine for display, but detailed allocation needs original source line IDs or unaggregated rows.
- If multiple stock rows use different currencies, CO needs a conversion rule before summing values. Without that rule, mark valuation as incomplete instead of silently summing.
- A single import lot can be needed by multiple products in the same dossier. Allocation must be case-level, not material-row-local, so the second product sees remaining quantity after the first product's allocation within the same snapshot.
- Existing hidden form parsing and persisted case snapshots need to round-trip `allocation_lines`; otherwise recalculation/export can collapse back to one row.
- Existing Excel/input workbook formats only have one source row per material. Export can be expanded safely, but import compatibility needs a transition plan.
- True “remaining C/O stock” across many dossiers requires a ledger/reservation model. CO cannot infer that from BCCT rows alone because Data Hub currently returns source rows, not committed consumption.

## Open Questions
- Should allocation order be FIFO by declaration date/source order, by lowest unit value, by highest available quantity, or manual/user-selected?
- When one NVL is sourced from multiple lots, should the main table stay one BOM row with expandable lot details, or should the bảng kê output duplicate that NVL into multiple source rows?
- Should phase one allocate within only the current dossier snapshot, or should saved dossiers reserve stock globally?
- If global reservation is required, should the ledger live in CO case state or Data Hub?
- How should mixed currencies be handled for VNM: block, use customs VND value only, or apply customs exchange rates?
- Should shortages still calculate temporary LVC from covered quantities, or should missing quantity be treated like missing unit price with a visible partial result?

## Recommended Next Step
- Implement phase one with tests first:
  - add a pure allocation helper for multiple stock rows
  - update origin product building to pass a mutable case-level allocation pool
  - add `allocation_lines` to material snapshots and hidden form round-trips
  - update the web table to show a compact source summary with expandable/tooltip details
  - expand dossier XLSX `LVC Statement`/`Origin Snapshot` allocation trace rows
- Defer global stock reservation until the product decision is made. If global reservation must be Data Hub-owned, create a Data Hub API request artifact before implementation.
