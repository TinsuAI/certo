# Session: 2026-05-03 — Source data inventory + project handoff

## What Was Done

Started by getting current with the project per session-start rules:

- Read `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Checked current git state and recent commits.
- Started from the existing dev server instead of launching a duplicate. Data Hub is live at `http://127.0.0.1:8754`.
- Verified `/` returns `302`.
- Ran tests: `361 passed, 15 skipped`.

Read the latest Claude Code history for this repo. The latest Claude session was in `~/.claude/projects/-home-vp-workspace-client-data-hub/3a4d044b-47ea-40ce-8f9e-fd866804b81e.jsonl`. Claude had finished Sprint A-D parser/data work and was interrupted after the user asked how many Growatt ghost BOM codes BQD could resolve.

Finished that interrupted measurement:

- Growatt has 2,440 distinct BOM material codes in Data Hub.
- 2,434 are not present in `hub.materials`.
- The two BQD archive files resolve 2,234 of those by `internal_code`.
- 200 remain unresolved.
- Current DB `hub.code_mappings` exactly matches the archive calculation.

Explored historical client data across sibling projects using subagents plus local scans:

- BCQT sources: `BCQT-System`, `bcqt-growatt`, `BCQT-DKE`, `bcqt-dothanh`.
- CO/Barry sources: `barry-CO-data`, `barry-CO-main`, `barry`, `barry-google-app`, `barry-CO-bom-data`.
- Current Data Hub ingestion surface: BCCT, Catalog/materials, BQD/code mappings, BOM/technical flatten.

Created a reproducible inventory script:

- `scripts/inventory_source_data.py`
- Scans curated sibling roots under `/home/vp/workspace/client`.
- Indexes `.xls`, `.xlsx`, `.xlsm`, `.csv`, `.json`.
- Infers client/kind/feedability from paths.
- Probes candidate Excel files with current Data Hub parsers.
- Writes local generated artifacts to `data/source_inventory/`.

Generated local inventory output:

- `data/source_inventory/source_roots.csv`
- `data/source_inventory/manifest.csv`
- `data/source_inventory/feedable_candidates.csv`
- `data/source_inventory/README.md`

Inventory results:

- 24 source roots scanned.
- 4,076 data files indexed.
- 89 `direct_feed_ready`.
- 19 `parser_ok_but_generated_source`.
- 1,377 `needs_parser_or_mapping`.
- 16 `needs_csv_adapter_or_conversion`.
- 398 `not_current_data_hub_scope`.

Added `data/source_inventory/` to `.gitignore` because the output is local cross-repo metadata, not project source.

Wrote discovery brief:

- `.ai/features/2026-05-03-source-data-inventory.md`

## Decisions Made

- Do not copy or reorganize raw multi-GB client corpora into Data Hub. Keep source files in their original sibling repos and organize via inventory/staging metadata.
- Treat only raw agency/HQ/master-data workbooks as canonical intake candidates.
- Treat generated BCQT/CO outputs (`cases/`, `derived/`, normalized CSVs, RVC/replacement outputs, settlement forms, `Johnson/output/CLEAN_*`) as reference/oracle data unless explicitly approved as a backfill source.
- Do not bulk-import every parser-OK file. Parser success proves shape compatibility, not source-of-truth correctness.
- Keep inventory output gitignored but keep the script and discovery brief in the repo.

## What Didn't Work

- First `uv run python scripts/inventory_source_data.py` failed because Python put `scripts/` on `sys.path`, so `app` was not importable. Fixed by adding the repo root to `sys.path` inside the script.
- Full probing took a few minutes and produced no progress output until completion. This is acceptable for now but should be improved if the inventory grows or becomes part of a routine workflow.
- A first attempt to interrupt the long-running inventory via tool stdin failed because stdin was closed. The process finished on its own shortly after and wrote all artifacts.

## Open Items

- Pick canonical source batches from `data/source_inventory/feedable_candidates.csv` before importing into Data Hub.
- Build a smoke/import runner only after source-of-truth choices are made per client/module.
- Parser follow-ups:
  - DS SP / TP-BTP catalog files rejected by current material parser.
  - DKE BOM/định mức files rejected by current BOM adapters.
  - CO `ToKhaiHQ7*` per-declaration files need a separate adapter and policy.
  - CSV normalized/cleaned files need explicit CSV support or one-time conversion.
- Decide how to resolve `unknown` client IDs in BCQT-System project uploads.
- Continue CO migration work before the 2026-05-16 cutoff.
