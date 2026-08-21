# Feature: Data views — pagination, sort, filter + DB-layer cleanup

**Date:** 2026-05-04
**Slug:** `data-views-pagination`
**Type:** UX + perf, bundled.

## Problem

User-reported: "các view dữ liệu giờ không có filter, pagination, etc gì
cả, và đặc biệt là app rất chậm." Verified on running server with
growatt-vn (largest tenant — 3,185 BCCT rows, 76 materials, 23.9k BOM
rows, 33.8k history events):

| View | Wall time | Page size | Diagnosis |
|---|---|---|---|
| `/clients/growatt-vn/bcct` | 150–200 ms | **773 KB** HTML | LIMIT 1000 rows rendered in one DOM |
| `/clients/growatt-vn/catalog` | 110 ms | small | OK volume; no pagination still |
| `/clients/growatt-vn/bom` | 90 ms | small | OK |
| `/clients/growatt-vn/bqd` | not measured | — | LIMIT 2000 hard cap |

Single search box + filter chips exist in some views but no pagination
anywhere; no sortable columns; one connection per query (no pool).

## Scope

### IN

**Slice A — UX (paginate + sort + single-search):**

1. Add `?page=N&page_size=50&sort=<col>&dir=<asc|desc>&q=...` to all
   four list views: BCCT, catalog, BQD, BOM products.
2. Default `page_size=50`. Allow `25 / 50 / 100 / 200` switcher; clamp
   server-side to ≤200.
3. Pagination footer shared partial: prev / next / first / last,
   total-count display, jump-to-page input. Preserves all other query
   params on each link.
4. Sortable column headers — click toggles `asc/desc`. Whitelist of
   sortable columns per view (no free-form column name from URL):
   - BCCT: `registration_date` (default desc), `declaration_no`,
     `customs_code`, `internal_code`.
   - catalog: `customs_code` (default asc), `internal_code`, `name`,
     `category`, `updated_at`.
   - BQD: `internal_code` (default asc), `customs_code`, `created_at`.
   - BOM: `last_published` (default desc), `product_code`, `n_versions`.
5. Single search box (existing pattern). No column-level filter.
6. Existing chip-row filters (BCCT direction/year, catalog
   category/provenance) continue to work, compose with pagination +
   sort + q.

**Slice B — DB layer cleanup (perf + future-proof):**

1. Connection pool via `psycopg_pool.ConnectionPool` (already a
   sub-package of psycopg 3.2 — no new dependency). Mounted on
   `app.state.db_pool` at FastAPI lifespan. `database.connect()`
   refactored to acquire-from-pool / return-on-close.
2. `stats_for_client` (`app/routes/clients.py:58`) — collapse 5
   sequential queries to 1 SQL with sub-aggregates.
3. `tab_freshness` (`app/stores/staleness.py:34`) — collapse 2
   sequential queries to 1.
4. New index `idx_bcct_client_regdate` on
   `hub.bcct_rows(client_id, registration_date desc, declaration_no, line_no)`
   — replaces the Seq Scan currently driving the BCCT list ORDER BY.
5. New `count(*) over ()` window in each list query OR a separate
   `select count(*)` — pick whichever the planner uses better. Decision
   taken during implementation.

### OUT (push to BACKLOG)

- Column-level filtering (per-column text/number/date filters in a
  filter row above the grid).
- Server-Sent Events / live-update on data change.
- Saved filter presets per user.
- CSV export of current filtered/sorted view.
- Lazy/virtual scrolling instead of paged display.

These all became candidate ideas during the discussion; explicitly
deferred. Logged in `.ai/BACKLOG.md` after this brief lands.

## Decisions

- **Page size 50 default** (user choice). Switcher 25/50/100/200.
- **Offset-based pagination** for HTML views (not cursor). Cursor is
  better for infinite scroll APIs; offset is conventional + cheaper to
  reason about for UI with prev/next/page-jump. The JSON API in
  `app/routes/api.py:206` already has cursor pagination — leave that
  alone.
- **Pool size** 8–16 (small VPS, 3 systemd units sharing Postgres).
  Open question — pin during impl after measuring uvicorn worker count.
- **No external dep added.** `psycopg_pool` ships with psycopg 3.2
  family; verify `import psycopg_pool` works against the pinned binary
  wheel. If not, add to pyproject as the only new dep.
- **Bundle A + B in one PR** because pagination perf wins are
  partially eaten by the per-page connect overhead — shipping A alone
  would feel less impactful, and the index in B unblocks the BCCT
  ORDER BY.
- **Sort is whitelist-only** — `sort=` param maps to a fixed dict of
  `{name: SQL fragment}` per view. No SQL injection surface even though
  every existing query already parameterizes values.
- **Search `q=`** keeps the existing semantics per view — ILIKE on the
  same column set as today. Don't expand search columns in this PR.

## Risks

1. **Pool lifecycle bugs.** `connect()` is used as a context manager
   in ~70 call sites; pool wrapper must preserve that contract. Risk:
   forgetting to return connection on exception path. Mitigation: keep
   `connect()` signature identical; pool returns a connection-proxy
   that releases on close, never destroys.
2. **`set_config('app.user_id', ...)` LOCAL vs SESSION.** Today
   migration sets it at SESSION scope (per-connect). Pooling reuses
   connections — leaking user_id from request N to request N+1 is a
   correctness risk for the BCCT history trigger. Fix: when a pool is
   used, switch to `set_config('app.user_id', ..., true)` (LOCAL) and
   wrap session-scoped writes in an explicit transaction. Already
   flagged in BACKLOG.
3. **Total-count cost on large BCCT.** A separate `count(*)` for
   pagination footer is another Seq Scan today. The new
   `idx_bcct_client_regdate` covers it. Validate via EXPLAIN before
   shipping.
4. **Existing tests.** 401 tests pass at HEAD. Many test the list
   route ignoring the response shape, but a few assert specific row
   counts ("upload N rows then list returns N"). Pagination changes
   those — adjust tests to call `?page_size=200`.
5. **Backward compatibility for query strings.** Existing
   chip-row filters use `?direction=...` etc. The new params are
   additive — must preserve all existing query params when building
   pagination/sort links. Risk: lose `q` when clicking page 2.
   Mitigation: shared `pagination_links(request, base_query)` helper
   that re-emits all current params except the one being overridden.

## Implementation order

1. Migration `028_bcct_client_regdate_index.sql` — create the new
   index. Validate EXPLAIN improvement.
2. `app/database.py` — introduce pool, keep `connect()` API.
3. `app/stores/clients.py` + `app/stores/staleness.py` — collapse
   multi-query helpers to single SQL.
4. New shared module `app/routes/_paging.py` — params parser, sort
   whitelist helper, count-and-page SQL builder, link builder.
5. New shared template partial `clients/_pagination.html` — footer
   with prev/next/first/last + page-size switcher.
6. Wire each of the 4 list views (BCCT, catalog, BQD, BOM) — each is
   independent, ship as its own slice if needed.
7. Tests:
   - Unit tests for `_paging.py` (param parsing, clamping, sort
     whitelist).
   - One integration test per list view: seed >50 rows, assert page
     1 has 50, page 2 has remainder, total count correct, sort
     respected, q filter narrows count.
8. Manual smoke + screenshot walk on growatt-vn (largest dataset).

## Open Questions

1. **Pool size.** Pin after checking uvicorn worker count
   (`UVICORN_WORKERS` env or default 1 on dev). For 1 worker → 8 is
   plenty; for prod with multiple workers may bump to 16.
2. **Total count strategy.** `count(*) over ()` window adds overhead
   per row; separate `select count(*)` adds 1 query but planner
   handles it well with the new index. Decide in impl after EXPLAIN.
3. **BOM products list paginated?** Current `list_products_with_bom`
   doesn't have a LIMIT — relies on small N (215 versions, ≤50
   distinct products per client today). Add pagination skeleton for
   parity OR mark as "small enough, skip"? Lean toward parity to keep
   the 4 views uniform.
4. **stats_for_client** returns counts shown in nav badges. If we
   collapse to single SQL, also cache it per-request (FastAPI
   dependency cache) so the same page render doesn't re-hit it from
   nav + page header? Out of scope, but worth a note.

## Done criteria

- All 4 list views support `?page=&page_size=&sort=&dir=&q=` plus
  existing chips.
- Pagination footer present on all 4 with total count + nav controls.
- `growatt-vn` BCCT page (largest dataset): full HTML <100KB,
  wall time <80ms p50.
- `psycopg_pool.ConnectionPool` mounted; no `psycopg.connect()` calls
  outside the pool except inside the migration runner (which boots
  before the pool exists).
- `idx_bcct_client_regdate` migration applied; EXPLAIN shows Index
  Scan instead of Seq Scan on the BCCT list query.
- Test suite passes (target: 401 + ~12 new = ~413 passed).
- Manual screenshot walk: 4 views × (page 1 + page 2 + sorted +
  filtered) committed under
  `.ai/features/2026-05-04-data-views-pagination/screenshots/`.

## Manual test plan

1. `growatt-vn` BCCT — load page 1, verify 50 rows + total ~3185.
2. Click `Tiếp` → page 2, URL contains `?page=2&page_size=50`, scroll
   position resets, 50 different rows.
3. Click column header `Ngày ĐK` → sort flips desc/asc, URL
   `?sort=registration_date&dir=asc`.
4. Type in search box → submit. Total drops; pagination updates.
5. Combine: `?direction=import&year=2024&q=NK&page=2&page_size=100&sort=customs_code&dir=asc`.
6. Repeat 1-5 on catalog, BQD, BOM pages with the relevant
   sortable columns.
7. Server log shows ~4–5 connections per page render (down from 7+),
   from the pool. No "connection refused" or pool-exhausted errors
   under rapid F5.

## Next step recommendation

`/tdd` for the implementation. Slice as: B1 (pool) → B2 (single-SQL
helpers + index) → A1 (paging module + first view: BCCT) → A2-A4
(catalog, BQD, BOM views). 5 slices, each its own commit.
