# Project Status

**Date:** 2026-05-04 (handoff after BOM raw-edge + demo-company feed)

## Current State

Data Hub has two new committed pieces of work:

- BOM can now store technical raw BOM graphs as direct `parent -> child`
  edges in `hub.bom_edges`, while existing flat/manual BOM rows remain in
  `hub.bom_version_rows`.
- One demo company has been generated and fed through the live web UI:
  `demo-precision-manufactu-480e` / `Demo Precision Manufacturing VN`.

The demo company exists in the local dev DB and is ready for API consumers:
catalog 50 rows, BQD 50 identity pairs, BCCT 1,000 rows, and 15 flattened
BOM products with 0 unresolved nodes.

Latest verification:

- `uv run pytest -q tests/test_bom_raw_edges.py tests/test_bom_flexible_flow.py tests/test_flatten_upload.py`
  -> **21 passed**
- `uv run pytest -q` -> **443 passed, 15 skipped**
- `uv run python -m py_compile scripts/feed_demo_company.py` -> pass
- `/healthz` on `http://127.0.0.1:8754` -> `200 {"status":"ok"}`
- API smoke for demo company -> pass; see
  `.ai/features/2026-05-04-demo-company-feed/reports/api_smoke.json`

Latest work commits before this handoff:

- `e5f59d6 chore(demo): add UI-fed demo company data pack`
- `2175847 feat(bom): store technical raw edges`

## Recent Changes

- Added migration `db/migrations/029_bom_raw_edges.sql`.
- Added raw-edge parser `app/parsers/bom_edges.py` for Growatt factory
  technical BOMs and Johnson/SAP indented BOMs.
- Added `technical_raw` BOM upload profile, raw-edge preview/confirm, and
  edge display on BOM version detail.
- Added raw BOM persistence helpers in `app/stores/bom.py`.
- Added tests in `tests/test_bom_raw_edges.py`.
- Added `scripts/feed_demo_company.py` to generate deterministic demo Excel
  inputs and drive the real web UI through client creation, config, catalog,
  BQD, BCCT, and BOM uploads.
- Added demo artifacts under
  `.ai/features/2026-05-04-demo-company-feed/`: input Excel files, feature
  briefs, expected-count test files, screenshots, manifest, DB summary, API
  smoke, and run notes.

## Next Steps

1. Decide whether to keep the local duplicate archive
   `.ai/features/2026-05-04-demo-company-feed.zip`; it is not needed because
   the committed feature folder contains the source artifacts.
2. Continue the BOM plan: generate flat versions from ingested raw graphs for
   Growatt/Johnson real data, including first-class BTP variants where needed.
3. If the demo company should be reproducible on a fresh DB, run
   `uv run python scripts/feed_demo_company.py` with the dev server live on
   port 8754.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when the user writes Vietnamese.
- Dev port **8754 is non-negotiable**. If occupied, stop the existing process;
  do not start another port.
- The local dev DB has already been mutated by the demo feed and earlier real
  BOM trial ingest. Git commits will not carry DB rows; rerun scripts for a
  fresh database.
- The first BQD demo upload failed because `hub.code_mappings.category` accepts
  only `nvl|tp|ccdc`, while the generated BQD had `btp_sx`. The generator now
  maps BTP rows to `tp` for BQD only, the stale pending was rejected through
  UI, and the corrected BQD upload succeeded.
- `.ai/features/2026-05-04-demo-company-feed.zip` appeared as an untracked
  duplicate archive after the demo folder was created. It was intentionally not
  used by the feed script.
