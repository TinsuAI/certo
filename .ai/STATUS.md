# Project Status

**Date:** 2026-05-03 (late session)

## Current State

Data Hub MVP web app is running and broadly functional: client workspaces, upload preview/confirm flows, SSO/session auth + JWT/service tokens, read APIs, BCCT confirm-on-update + history, LLM smart parser, BQD/catalog/BOM upload flows, BOM proposal modes, technical BOM flattening, catalog provenance/staleness signals, and CO-facing API contract guardrails.

Latest committed HEAD is `6bb0866 docs(backlog): Sprint D parser/data architectural follow-ups`. The worktree currently has uncommitted handoff/session and source-inventory changes from this session.

Dev server is running at `http://127.0.0.1:8754` (required port). `/` returns `302`. Test suite verified this session: **361 passed, 15 skipped**.

## Recent Changes

- Read project handoff files, recent session summaries, and the latest Claude Code session history.
- Confirmed Claude's last interrupted task: measure how many Growatt BOM ghost codes are resolved by BQD archive files.
- Measured Growatt resolution state:
  - 2,440 distinct BOM material codes.
  - 2,434 not present in `hub.materials`.
  - BQD archive resolves 2,234 of those by `internal_code`.
  - 200 remain unresolved; DB `hub.code_mappings` current state matches this exactly.
- Created a historical source-data inventory flow:
  - `scripts/inventory_source_data.py` scans sibling project roots and probes candidate Excel files with current Data Hub parsers.
  - Generated local artifacts under `data/source_inventory/` (`manifest.csv`, `feedable_candidates.csv`, `source_roots.csv`, `README.md`).
  - Added `data/source_inventory/` to `.gitignore` because it is local cross-repo inventory output.
  - Wrote discovery brief `.ai/features/2026-05-03-source-data-inventory.md`.
- Source inventory scanned 24 source roots and indexed 4,076 data files:
  - `direct_feed_ready`: 89 files.
  - `parser_ok_but_generated_source`: 19 files.
  - `needs_parser_or_mapping`: 1,377 files.
  - `needs_csv_adapter_or_conversion`: 16 files.
  - `not_current_data_hub_scope`: 398 files.

## Next Steps

1. Review `data/source_inventory/feedable_candidates.csv` and select one canonical intake batch per client/module before importing anything into the DB.
2. Prioritize raw source feeds:
   - Growatt BCCT/BQD/BOM from `bcqt-growatt/data`.
   - Growatt/Johnson supplier BOMs from `barry-CO-data/extracted/CO/bom-supplier-zips` and `barry-CO-bom-data/extracted`.
   - DKE BCCT + DS NPL from `BCQT-DKE/input`.
   - Do Thanh BCCT E31/E62 from `bcqt-dothanh/data`.
   - Johnson raw docs from `Johnson/docs`.
3. Treat `barry-CO-data/cases`, `barry-CO-data/derived`, normalized CSVs, RVC/replacement outputs, BCQT settlement outputs, and `Johnson/output/CLEAN_*` as reference/oracle data unless explicitly approved as backfill input.
4. If bulk intake is desired, build a dedicated smoke/import script that consumes the shortlist and runs through Data Hub's existing preview/confirm semantics. Do not bypass source-of-truth decisions.
5. Parser backlog from inventory:
   - DS SP / TP-BTP catalog shapes that current `parse_materials_workbook()` rejects.
   - DKE BOM/định mức adapters.
   - CO per-declaration `ToKhaiHQ7*` adapter and policy (BCCT vs CO evidence).
   - Optional CSV adapters for cleaned/reference data.
6. CO migration cutover remains due by 2026-05-16; consumers must handle the BOM flatten contract and service-account JWT adoption before strict auth.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when the user writes Vietnamese.
- Dev port **8754 is non-negotiable**. If already running, use it; do not start Data Hub on another port.
- Current server process: `uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload`.
- `data/source_inventory/` is gitignored generated output; regenerate with:
  `uv run python scripts/inventory_source_data.py`
- Full parser probing over many Excel workbooks can take a few minutes and may appear quiet because the script writes at the end.
- `scripts/inventory_source_data.py` was syntax-checked with `uv run python -m py_compile scripts/inventory_source_data.py`.
- Do not copy multi-GB sibling corpora into this repo. Keep raw files in place and use metadata/staging/indexes.
- Current uncommitted files after handoff should include `.gitignore`, `.ai/STATUS.md`, `.ai/features/2026-05-03-source-data-inventory.md`, `.ai/sessions/2026-05-03-source-data-inventory.md`, and `scripts/inventory_source_data.py`.
