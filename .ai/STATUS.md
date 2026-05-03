# Project Status

**Date:** 2026-05-04 (handoff after data-views pagination/perf sprint)

## Current State

Data Hub is on `main` with a clean implementation of the data-views
pagination/perf sprint. The 4 main client data tabs now have paginated,
searchable, sortable list views:

- BCCT
- Catalog / Danh Mục
- BQD / Mã Quy Đổi
- BOM products

The DB perf cleanup for those views also shipped: pooled Postgres
connections, collapsed client stats/freshness queries, and a BCCT
registration-date index.

The earlier unified flexible upload flow remains shipped across catalog,
BQD, BOM-manual_flat, and BCCT. The list-view work did not change upload
or read API contracts.

Latest verification:

- `uv run pytest -q` -> **437 passed, 15 skipped**
- `uv run python scripts/screenshot_paginated_views.py` -> **16 PNGs**
  under `.ai/features/2026-05-04-data-views-pagination/screenshots/`
- Live smoke: `http://127.0.0.1:8754/` returns `302`

Latest work commits before this handoff:

- `0555b0a docs(views): screenshot walk for paginated data views`
- `bb7ed68 feat(views): slice A4 - BOM products paginate + search + sortable headers`
- `42de56d feat(views): slice A3 - BQD paginate + search + sortable headers`
- `f53d9bc feat(views): slice A2 - catalog paginate + sortable headers`
- `deb506f feat(views): slice A1 - pagination + sort + footer (BCCT first)`
- `c7df89a perf(db): slice B2 - collapse stats/freshness to single SQL + bcct index`
- `055b9d4 feat(db): slice B1 - psycopg connection pool with reset-on-checkin`

## Recent Changes

- Claude Code completed the data-views implementation slices B1, B2, A1,
  A2, A3, and A4, then hit usage limit after creating an untracked
  `scripts/screenshot_paginated_views.py`.
- Codex read Claude Code history, confirmed the interrupted state, and
  completed the remaining evidence/handoff work.
- `scripts/screenshot_paginated_views.py` now logs PNG sizes and captures
  4 states per module: page 1, page 2, alternate sort, filtered `q=`.
- Committed 16 desktop Playwright screenshots for the paginated views.
- Updated `.ai/sessions/2026-05-04-data-views-pagination.md` with the full
  cross-tool session history.

## Next Steps

1. Run real-data smoke against the 21 catalog rejects in
   `data/source_inventory/feedable_candidates.csv`.
2. Add English rigid aliases for BQD and BOM headers so English-only files
   can rigid-match without staff manually mapping columns.
3. Triage the 200 unresolved Growatt BOM material codes.
4. Consider per-client module required-fields overrides if client-specific
   parser policy becomes necessary.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when the user writes Vietnamese.
- Dev port **8754 is non-negotiable**. If occupied, stop the existing
  process; do not start on another port.
- `app/routes/_paging.py` owns pagination, page-size clamping, sort
  whitelist resolution, and link building.
- `app/templates/clients/_pagination.html` is the shared footer.
- Keep sort columns whitelist-only. Never splice raw query params into SQL.
- `app/database.py` now pools default DB connections. Custom `url=...`
  connections still bypass the pool for tests/scripts.
- Pool reset clears `app.user_id` on check-in for BCCT history trigger
  attribution. Do not remove it unless that attribution model changes.
- `scripts/screenshot_paginated_views.py` assumes the dev server is live on
  `http://127.0.0.1:8754`.
- `app/routes/_mapping_flow.py` and `_llm_fallback.py` are both still live.
  Do not delete `_llm_fallback.py`; BOM layout-driven adapters and BCCT
  cache-hit paths still use it.
