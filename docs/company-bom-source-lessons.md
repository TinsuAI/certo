# Company BOM Source Lessons

This note ports the useful BOM-source lessons from the `feature/bom-builder` worktree back into this project.
It intentionally records semantics and aggregate findings only; raw client files stay in local data folders.

## Source Families

### Technical BOM

Supplier-provided engineering BOM files.
These may come from ERP or SAP exports and can be multi-level:

- finished product -> semi-finished assemblies -> materials
- a component is a branch when it has child rows in the same BOM tree
- a component is a leaf when it has no child rows
- flattened BOM should normally consume leaf materials only
- a semi-finished item should be consumed directly only when it is confirmed as purchased or imported
- BOM files are snapshots at a point in time unless explicit version fields prove otherwise

Technical BOM is product-structure evidence.
It is not stock evidence and does not prove that a material lot is import-eligible for a C/O case.

### DS NVL DK HQ

Customs-registered material list downloaded from customs or ECUS.
It is the reference catalog of material/input codes declared to customs.

In theory, imported material codes in `BCCT` should exist here.
In practice, the system must tolerate registration mistakes, delayed maintenance, and unregistered transaction codes.

### DS SP DK HQ

Customs-registered finished product list downloaded from customs or ECUS.
It is the reference catalog of exported product codes declared to customs.

In theory, exported product codes in `BCCT` should exist here.

### BCCT

Detailed customs declaration report downloaded from customs or ECUS.
It contains import and export declaration lines and includes NPL/SP codes per line.

Use `BCCT` as transaction evidence, not as the canonical catalog by itself.

## Company Profiles Observed

### Growatt

Growatt data is a mixed-source technical BOM family.
The observed BOM files include finished-product BOM workbooks and semi-finished-product BOM workbooks.
The parser treats both as potential parent nodes in a graph and flattens finished products across workbooks until it reaches leaf components.

Useful source facts:

- Growatt workbook headers are Chinese SAP/ERP-style fields such as finished material, component material, unit, standard usage, alternative group, priority, strategy, and usage probability.
- Finished BOM and BTP BOM live in separate source folders, so source family and file name both matter.
- Exact-code BTP workbook candidates should be preferred when a component code also appears inside a finished-product workbook.
- Cyclic BOM references must fail fast rather than silently flatten.
- Repeated leaf components are aggregated per root product, leaf component, unit, and source workbook while keeping path count and sample path as audit evidence.

Current useful derived dataset:

- `9` Growatt priority finished-product codes were flattened from 2025 cross-workbook sources.
- All `9` priority codes flattened with `0` unresolved parent components.
- Flattened material counts by product ranged from `274` to `482` rows in the cross-workbook manifest.
- The same `9` products were compared against the customs-registered material list.
- Every compared product had differences between flattened technical BOM and registered material list: only-in-technical-BOM rows, only-in-registered-list rows, and quantity deltas.

Design implication:
Growatt cannot be modeled as one trusted workbook per product.
It needs source selection, parent/child graph flattening, BTP treatment, code reconciliation, and operator review.

### Johnson

Johnson data is a stable SAP-export family.
The observed source batch contains `82` `.XLSX` workbooks with one useful `Sheet1` each and a shared `29`-column SAP-style header.
Workbook metadata identifies the creator as `SAP WebAS`.

Useful source facts:

- The batch behaves like one export snapshot.
- There is no reliable workbook-level BOM version field.
- File name is currently the practical exported-product key.
- `Level` and `Explosion level` reconstruct the hierarchy from row order.
- `Comp. Qty (CUn)` is the safest flattened quantity in this export.
- Recomputed hierarchy multiplication should still be kept as a validation check.
- `Revision Level` and `Change Number` are line-level change evidence, not workbook-level BOM versions.

Current useful derived dataset:

- workbooks: `82`
- aggregate source rows: `22,800`
- structural leaf rows: `14,289`
- material-candidate leaf rows: `13,882`
- structural rollup rows: `9,616`
- material-candidate rollup rows: `9,209`
- maximum depth: `8`
- level/explosion mismatches: `0`
- invalid hierarchy jumps: `0`
- quantity deltas over tolerance: `0`
- bulk leaf rows: `2,753`
- base-unit/component-unit mismatches: `2,764`
- duplicate display paths: `8`

Johnson emits two leaf families:

- structural leaves: every leaf in the SAP hierarchy
- material-candidate leaves: structural leaves after excluding obvious document-like rows such as drawings, renderings, diagrams, and assembly views

Design implication:
Johnson can start with a source-specific SAP importer.
It should still preserve all source fields, structural paths, SAP line change signals, and validation metrics because material-candidate filtering is heuristic.

## Importer Requirements For This Project

- Treat BOM importers as source-family specific.
- Keep raw uploaded file, parsed snapshot, reviewed rows, and published version separate.
- Keep file fingerprint, BOM family identity, and published version identity separate.
- Preserve source rows and exact codes as text.
- Preserve branch rows, leaf rows, and flattened leaf outputs.
- Do not auto-deduplicate repeated rows or repeated blocks without operator review.
- Store rollup policy with the output, including dedupe mode and unit conversions.
- Keep validation metrics as review signals, not automatic pass/fail decisions.
- Keep Technical BOM, DS NVL DK HQ, DS SP DK HQ, and BCCT as separate source types.

## App Implications

The current CO demo should represent BOM as a client data module with source profiles, not only a flat list of material rows.
At minimum, the app should distinguish:

- Growatt-style multi-workbook BOM graph with finished-product and BTP sources.
- Johnson-style SAP exploded BOM export with hierarchy levels and cumulative quantities.
- Customs catalogs from DS NVL/DS SP.
- Transaction evidence from BCCT.

The C/O case view should consume reviewed/published BOM evidence and CO stock evidence.
It should not mutate source BOM semantics while evaluating RVC/CTSH.
