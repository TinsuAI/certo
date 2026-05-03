# Project Status

**Date:** 2026-05-04 (end of data-views pagination/perf sprint + screenshot walk)

## Current State

The **data list views are now paginated, searchable, and sortable** across
all 4 main client data tabs: BCCT, catalog, BQD, and BOM products.
The perf cleanup slice also landed: pooled Postgres connections, collapsed
client stats/freshness queries, and the BCCT list index.

The previous **unified flexible upload flow** remains shipped end-to-end
across catalog + BQD + BOM-manual_flat + BCCT. The new list-view work did
not change upload/API contracts.

Dev server expected at `http://127.0.0.1:8754` (required port).
Latest verification:

- `uv run pytest -q` -> **437 passed, 15 skipped**
- `uv run python scripts/screenshot_paginated_views.py` -> **16 PNGs**
  under `.ai/features/2026-05-04-data-views-pagination/screenshots/`
- Live root smoke: `/` returns `302` on port 8754

HEAD trail before the final screenshot/status commit (newest first):

- `bb7ed68 feat(views): slice A4 - BOM products paginate + search + sortable headers`
- `42de56d feat(views): slice A3 - BQD paginate + search + sortable headers`
- `f53d9bc feat(views): slice A2 - catalog paginate + sortable headers`
- `deb506f feat(views): slice A1 - pagination + sort + footer (BCCT first)`
- `c7df89a perf(db): slice B2 - collapse stats/freshness to single SQL + bcct index`
- `055b9d4 feat(db): slice B1 - psycopg connection pool with reset-on-checkin`
- `3f06586 docs(uploads): screenshot walk for unified upload flow`

## Recent Changes (2026-05-04 data views sprint)

- Wrote feature brief
  `.ai/features/2026-05-04-data-views-pagination/brief.md` for pagination,
  sorting, search, and DB-layer cleanup.
- **Slice B1 (commit `055b9d4`)** - introduced
  `psycopg_pool.ConnectionPool`, kept `app.database.connect()` as the
  single app entrypoint, and added reset-on-checkin for `app.user_id`.
- **Slice B2 (commit `c7df89a`)** - collapsed `stats_for_client` and
  `freshness_for_template` DB work to fewer SQL calls and added
  `db/migrations/028_bcct_client_regdate_index.sql`.
- **Slice A1 (commit `deb506f`)** - added shared paging/sort helpers,
  shared pagination template, CSS, and BCCT list pagination/sort/search.
- **Slice A2 (commit `f53d9bc`)** - migrated catalog list to the shared
  pagination/sort/search shape while preserving category/provenance chips.
- **Slice A3 (commit `42de56d`)** - migrated BQD list to the shared
  pagination/sort/search shape.
- **Slice A4 (commit `bb7ed68`)** - migrated BOM products list to the
  shared pagination/sort/search shape, including product count and paged
  product aggregation store helpers.
- **Screenshot walk** - `scripts/screenshot_paginated_views.py` drives
  the live UI with Playwright and captures 4 states per module:
  page 1, page 2, sorted alternate column, filtered `q=`.

## Data Views Outcome

All 4 list views now support:

```text
?page=N&page_size=25|50|100|200&sort=<whitelisted-col>&dir=asc|desc&q=...
```

View-specific behavior:

- **BCCT**: default sort `registration_date desc`; sortable
  `registration_date`, `declaration_no`, `customs_code`, `internal_code`;
  existing `year` and `direction` chips compose with pagination/search.
- **Catalog**: default sort `customs_code asc`; sortable `customs_code`,
  `internal_code`, `name`, `category`, `updated_at`; existing category and
  provenance chips compose with pagination/search.
- **BQD**: default sort `internal_code asc`; sortable `internal_code`,
  `customs_code`, `created_at`; search over internal/customs codes.
- **BOM**: default sort keeps non-flattened products first, then latest
  publish time; sortable `last_published`, `product_code`, `n_versions`;
  search over product code.

## Previous Upload Flow Outcome

Across catalog + BQD + BOM-manual_flat + BCCT the upload flow uses the
same shape:

```text
POST /clients/{c}/<m>/upload
  -> save blob -> record_upload -> compute file_signature
  -> cache hit: parse -> preview
  -> cache miss: mapping page -> parse with overrides -> preview -> confirm
```

Module-specific notes:

- **catalog**: at least one of `customs_code` or `internal_code`; provenance
  toggle registered vs user_added.
- **BQD**: requires both `internal_code` and `customs_code`.
- **BOM-manual_flat**: requires `product_code`, `material_code`, and
  quantity by default; layout-driven adapters bypass the mapping page;
  technical_flatten unchanged.
- **BCCT**: requires `declaration_no`, `registration_date`, and
  `customs_code`; confirm-on-update and history semantics preserved.

## Not Done / Deferred

- Real-data smoke against the 21 catalog rejects in
  `data/source_inventory/feedable_candidates.csv`.
- English rigid aliases for BQD + BOM headers; mapping page + LLM still
  handles those, but rigid auto-match does not.
- Per-client module required-fields override.
- Column-level filters, saved filters, CSV export, live updates, and
  virtual scrolling for data views. These remain backlog ideas.
- Ghost-code triage: 200 unresolved Growatt BOM material codes from a
  prior session.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when the user writes Vietnamese.
- Dev port **8754 is non-negotiable**. If occupied, stop the existing
  process; do not start on another port.
- Latest known green suite: `437 passed, 15 skipped`.
- `app/routes/_paging.py` owns pagination, page-size clamping, sort
  whitelist resolution, and link building.
- `app/templates/clients/_pagination.html` is the shared footer.
- List views call `parse_page_params`, `SortSpec.from_params`,
  `pagination_context`, and `sort_link`.
- Keep sort columns whitelist-only. Do not splice raw query params into
  SQL fragments.
- `app/database.py` now pools default DB connections. Custom `url=...`
  connections still bypass the pool for tests/scripts.
- Pool reset clears `app.user_id` on check-in; do not remove it unless
  the BCCT history trigger attribution model changes.
- `scripts/screenshot_paginated_views.py` assumes the dev server is live
  on `http://127.0.0.1:8754` and logs PNG sizes after capture.
- `app/routes/_mapping_flow.py` and `_llm_fallback.py` are still both
  live. Do not delete `_llm_fallback.py`; BOM layout-driven adapters and
  BCCT cache-hit paths still use it.
