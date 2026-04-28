# Project Status

## Current State
- The FastAPI/Jinja C/O demo app now has client workspace views for overview, customs catalogs, BOM, C/O stock, BCCT, C/O case, and company config.
- Source tables use reusable advanced table rendering with server-side search, filters, sorting, pagination, and summary chips.
- Catalog is split into DS NVL and DS SP child views.
- BCCT is split into import/export child views. Export view respects the configured relevant export declaration types.
- Company config is file-backed and versioned by `config_version`/`config_hash`; Growatt defaults to DNCX imports `E11, E15`, export `E42`, and description-regex allocation-code extraction.
- C/O stock is derived from all BCCT import lines as stock candidates. Config no longer removes lines; it marks them `active`, `inactive`, or review-only. Inactive rows stay visible for audit with `remaining_qty = 0`.
- Runtime data remains local-only under `data/local/...`; screenshots and sample uploads remain under ignored `temp/`.

## Recent Changes
- Added `.ai/features/2026-04-29-client-config-bcct-code-reconciliation.md` to document the config, BCCT split, allocation-code, and C/O stock eligibility approach.
- Added `app/client_config_store.py` for client config defaults, validation, persistence, config hashing, and allocation-code resolution.
- Added reusable table helper/template files: `app/table_view.py`, `_advanced_table.html`, and `catalog_table.html`.
- Updated BCCT, C/O stock, config, catalog, and C/O case routes/templates to use the new config and table model.
- C/O stock now preserves `customs_item_code`, derives `allocation_code`, keeps `source_line_ids`, snapshots config hash/version, and separates active/inactive/review-required rows.
- Added regression coverage for config defaults, invalid regex, BCCT import/export route split, declaration-type normalization, stock eligibility deactivation/reactivation, aggregation traceability, unresolved/manual-review stock, export type filtering, and table behavior.
- UI was checked with Playwright screenshots under `temp/ui-checks/`; desktop/mobile rendered without console errors or horizontal overflow.

## Next Steps
1. Manually test the new config-driven stock eligibility flow in the browser: remove/re-add `E15` and confirm rows move between `Khả dụng` and `Không dùng` without disappearing.
2. Decide whether inactive/review-required stock should be visually separated into tabs or remain as a status filter in the same Tồn CO table.
3. Add case allocation logic that only consumes `active + resolved` C/O stock once C/O allocation moves beyond demo display.
4. Revisit whether `relevant_export_declaration_types` should also drive future export matching for C/O cases, not just the BCCT export view.

## Notes for Next AI Session
- Use `uv run pytest tests/test_co_demo.py -q` for the current CO app suite; last run: `65 passed`.
- `git diff --check` was clean before handoff.
- Dev server command: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8001`.
- Do not commit `data/` runtime state or `temp/` screenshots/uploads unless the user explicitly asks for sanitized fixtures.
- User prefers Vietnamese replies when writing Vietnamese; docs/artifacts stay in English unless client-facing.
