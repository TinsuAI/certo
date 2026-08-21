# Session 2026-05-04 — BOM raw graph + demo company feed

## What Was Done

- Implemented raw technical BOM storage alongside flat BOM rows.
  - Added `hub.bom_edges` via `db/migrations/029_bom_raw_edges.sql`.
  - Added `app/parsers/bom_edges.py` for Growatt factory technical
    parent-child rows and SAP/Johnson indented levels.
  - Added `create_raw_version`, raw-edge hashing, and `edges` return support
    in `app/stores/bom.py`.
  - Added BOM upload profile `technical_raw` and persisted raw edges from
    preview/confirm.
  - Added edge-table display on BOM version detail.
  - Added `tests/test_bom_raw_edges.py`.
- Trialed real raw BOM ingestion before this handoff:
  - Growatt supplemental technical files: 39 files parsed, 41 raw versions,
    16,456 edges, max depth 5, 0 disconnected edges after parser fixes.
  - Johnson technical files: 82 files parsed, 82 raw versions, 22,800 edges,
    max depth 8, 0 disconnected edges.
- Generated a deterministic demo company data pack under
  `.ai/features/2026-05-04-demo-company-feed/`.
  - Input Excel files: catalog 50 codes, BQD 50 identity pairs, BCCT 1,000
    rows, BOM 49 multi-level rows.
  - Per-feature folders: brief, tests/expected counts, screenshots.
  - Reports: manifest, final DB summary, API smoke, run notes.
- Fed the demo company through the live web UI on port 8754:
  - Created `demo-precision-manufactu-480e`.
  - Set identity code-resolution mode, auto BOM proposal mode, 3 percent
    tolerance, and declaration config `E11,E31` import plus `E62,B11` export.
  - Uploaded catalog, BQD, BCCT, and `technical_flatten` BOM through UI
    mapping/preview/confirm flows.
  - Captured screenshots for each feature and final readiness views.
- Verified final demo DB state:
  - Catalog: 50 rows (`34 nvl`, `7 btp_sx`, `8 tp`, `1 ccdc`).
  - BQD: 50 identity pairs.
  - BCCT: 1,000 rows (`650 import`, `350 export`).
  - BOM: 15 flattened products (`8 TP`, `7 BTP`), 97 flattened rows,
    0 unresolved nodes.
- Ran verification:
  - Targeted BOM tests: `21 passed`.
  - Full suite: `443 passed, 15 skipped`.
  - Script compile check: pass.
  - `/healthz`: 200.
  - Demo API smoke: pass.
- Committed the work in two focused commits before writing this handoff:
  - `2175847 feat(bom): store technical raw edges`
  - `e5f59d6 chore(demo): add UI-fed demo company data pack`

## Decisions Made

- Store raw BOM graphs in `hub.bom_edges`, not in `hub.bom_version_rows`.
  `bom_versions` remains the shared version/provenance table.
- Keep `technical_raw` separate from `technical_flatten`. Raw ingest preserves
  direct edges; flattening remains a distinct materialization step.
- Treat staff-converted GOM BOM files as flat/staff artifacts, not as source
  raw graph.
- For demo data, use `code_resolution_mode='identity'` and set
  `customs_code == internal_code` across all 50 catalog rows.
- For BQD only, map BTP categories to `tp` because the legacy
  `hub.code_mappings.category` enum is narrower than `hub.materials.category`.
- Use `technical_flatten` for the demo BOM so the final company is immediately
  calculation-ready for downstream apps.

## What Didn't Work

- First BQD demo upload confirmed through UI but hit a 500 because generated
  BQD rows carried category `btp_sx`, which violates
  `hub.code_mappings.chk_mapping_category`.
  - Fixed generator to emit `tp` for BTP rows in the BQD file only.
  - Rejected the stale pending upload through the UI.
  - Re-uploaded BQD through the UI and confirmed successfully.
- A scratch helper `app/flatten/raw_edges.py` had been started for future raw
  graph flattening but was not wired or tested. It was deleted before commit
  so no half-finished code is handed off.

## Open Items

- Materialize flat versions from real raw BOM graphs for Growatt and Johnson.
  The schema/parser side is ready; the raw-to-flat batch materialization still
  needs implementation.
- Decide whether BTP raw subgraphs should become first-class raw versions for
  Growatt. Earlier trial data showed repeated BTP definitions with conflicts,
  so do not dedupe solely by BTP code without variant/source context.
- The untracked duplicate archive
  `.ai/features/2026-05-04-demo-company-feed.zip` can be deleted or ignored;
  the folder artifact is the canonical result.
