# Feature: Historical Source Data Inventory

## Scope

Build a usable map of historical client data across sibling projects so Data Hub can ingest the right raw files and avoid treating generated settlement/CO outputs as canonical source.

This pass indexed metadata and parser probe results only. It did not copy, move, delete, or rename raw files in sibling repos.

Generated artifacts:

- `data/source_inventory/source_roots.csv` — scanned root counts.
- `data/source_inventory/manifest.csv` — all indexed `.xls`, `.xlsx`, `.xlsm`, `.csv`, `.json` files.
- `data/source_inventory/feedable_candidates.csv` — files that may feed Data Hub or require parser work.
- `data/source_inventory/README.md` — generated summary.
- `scripts/inventory_source_data.py` — reproducible inventory script.

`data/source_inventory/` is gitignored because it is local workspace inventory with cross-repo paths.

## Current Data Hub Intake Surface

Data Hub can currently ingest four business modules, all via Excel workbook uploads:

- BCCT: `parse_bcct_workbook()`
- Catalog / Danh Mục NVL-SP-BTP-CCDC: `parse_materials_workbook()`
- BQD / code mappings: `parse_code_mappings_workbook()`
- BOM: `parse_bom_workbook()` with adapter profiles, plus `technical_flatten`

CSV is not a business upload format today. CSV files are useful as oracle/reference data or require conversion/adapter work before canonical intake.

CO per-shipment declaration files (`ToKhaiHQ7*`) are not BCCT rollups. They mostly fail the BCCT parser today and should not be bulk-fed as canonical BCCT without a separate adapter and reconciliation design.

## Inventory Results

Scanned 24 source roots and indexed 4,076 data files:

- `bcqt-growatt/data`: raw Growatt BCQT archive, BOM TP/BTP, BCCT, BQD, Danh Mục.
- `barry-CO-data/extracted`: largest raw/extracted CO corpus; includes Growatt, Johnson, Do Thanh, Hong An folders, many per-declaration files, and supplier BOMs.
- `barry-CO-data/cases` and `barry-CO-data/derived`: generated normalized/RVC/replacement outputs, useful for tests and audit but not canonical Data Hub intake.
- `BCQT-DKE/input`: DKE BCCT, DS NPL/SP, mapping, BOM/định mức, ERP/inventory inputs.
- `bcqt-dothanh/data`: Do Thanh BCCT E31/E62 and inventory/reference workbooks; little master-data coverage.
- `Johnson/docs` / `Johnson/output`: raw docs plus many cleaned/generated outputs; raw docs are input candidates, cleaned outputs are reference unless intentionally backfilled.
- `barry/docs/sample-data` and `barry-google-app/docs/sample-data`: Growatt sample/raw copies useful for smoke and comparison.
- `barry-CO-main/temp` and `barry-CO-bom-data/local`: temp/manual fixtures; useful for tests, not source of truth.

Probe summary:

- `direct_feed_ready`: 89 files parsed by current Data Hub parsers.
- `parser_ok_but_generated_source`: 19 generated Excel outputs also parse, but should not be canonical without explicit approval.
- `needs_parser_or_mapping`: 1,377 files, dominated by CO per-declaration forms and client-specific workbook shapes.
- `needs_csv_adapter_or_conversion`: 16 files, including cleaned Johnson/CO normalized CSVs.
- `not_current_data_hub_scope`: 398 settlement/stock/RVC outputs.

## Feedable Now

Prioritize these raw-ish sources for Data Hub intake tests:

- Growatt BCCT: `bcqt-growatt/data/archive/BaoCaoHangChiTiet 01.01.2025 - 31.12.2025 08.01 or.xlsx`
- Growatt BQD: `bcqt-growatt/data/archive/BANG QUY DOI NVL (bao gom 1 ma NB - nhieu HQ).xlsx`
- Growatt BQD TP: `bcqt-growatt/data/archive/BANG QUY DOI THANH PHAM.xlsx`
- Growatt BOM aggregates: `bcqt-growatt/data/archive/GOM BOM TP.xlsx`, `bcqt-growatt/data/archive/GOM BOM BTP.xlsx`, `bcqt-growatt/data/archive/BOM/TONG HOP BOM TP 2025.xlsx`, `bcqt-growatt/data/archive/BOM - BTP/TONG HOP BOM BTP.xlsx`
- Growatt supplier BOMs: `barry-CO-data/extracted/CO/bom-supplier-zips` and `barry-CO-bom-data/extracted`
- DKE BCCT/catalog: `BCQT-DKE/input/.../BaoCaoHangChiTiet 2025 Official.xls`, `DS NPL KHAI BAO.xls`
- Do Thanh BCCT: `bcqt-dothanh/data/extracted/.../BaoCaoHangChiTiet E31...xls`, `BaoCaoHangChiTietE62.xls`
- Johnson raw BCCT/Q1 docs under `Johnson/docs`; generated `Johnson/output/CLEAN_*` is reference-only unless chosen for backfill.

## Needs Parser Or Mapping

These should be separate work items, not hidden inside a bulk import:

- DS SP / TP-BTP workbooks where columns are not recognized as `customs_code` or `internal_code`.
- DKE BOM/định mức workbooks, which fail current BOM adapters.
- CO per-shipment `ToKhaiHQ7*` declarations. They need an individual-declaration adapter and policy for whether they become BCCT rows or stay CO evidence.
- CSV normalized outputs from Johnson and CO cases. They need either CSV adapters or a conscious one-time conversion.

## Decisions

- Keep raw files in their original sibling repos. Do not duplicate multi-GB client corpora into Data Hub.
- Treat Data Hub intake as canonical only when the source is raw agency/HQ/master-data input, not generated BCQT/CO output.
- Use generated outputs as tests/oracles for parser correctness, flattening quality, and cross-system parity.
- Keep local inventory artifacts gitignored; regenerate from script when the workspace changes.

## Risks

- Path-based client inference is approximate. Some `unknown` files are real clients but need project DB/client metadata to resolve.
- Parser OK does not equal safe canonical import. A generated settlement output may parse as BCCT or BOM but still be the wrong source of truth.
- Many CO files are per-declaration evidence, not annual BCCT exports. Bulk importing them would re-open the MVP BCCT single-writer decision.
- Large Excel files can make full probing slow. The script is usable but may need batching if the corpus grows.

## Open Questions

- Should Data Hub add CSV import support for cleaned/reference datasets, or should those stay as test-only fixtures?
- Do we want a separate CO evidence/file-snapshot intake path before Phase 2 storage exists?
- Which client IDs should be assigned to currently `unknown` BCQT-System project uploads?
- For DKE BOM, should we build a new adapter now or defer until DKE becomes an active Data Hub client?

## Suggested Next Step

Use `data/source_inventory/feedable_candidates.csv` to pick one intake batch per client/module, then run Data Hub uploads manually or via a dedicated smoke script. Do not bulk-import all parser-OK files into the database without a per-client source-of-truth decision.
