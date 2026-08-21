# Feature: Catalog conflicts review page

Closes BACKLOG A.2. Catalog list already surfaces 2 inline badges per
row (⚠ Xét lại + ⚠ Conflict sourcing), but there is no dedicated
review queue showing only conflicting rows. Staff have to scroll the
full list and filter mentally. This adds a single page listing all
conflicts across both types with inline actions.

## Scope

**In:**

1. **GET `/clients/{cid}/catalog/conflicts`** — table page listing
   every material with `declared_observed_conflict=true` OR
   `sourcing_confirmation_conflict=true` (computed Python-side from
   `observed_roles[]` + `btp_sourcing`).
2. **Conflict-type filter** — chips: `Tất cả / Khai báo ≠ quan sát /
   Xác nhận nguồn ≠ quan sát`. Default `all`.
3. **Existing filters reused** — `category`, `provenance` (status
   filter not relevant — all rows are active anyway). Same widget
   shapes as the catalog list.
4. **Per-row columns** — `code`, `name`, `declared (category)`,
   `observed_roles[]`, `btp_sourcing (staff confirm)`,
   `suggested_sourcing`, `code_kind`, `source`. Plus per-row action:
   inline `btp_sourcing` dropdown (POSTs to existing
   `/btp_sourcing` endpoint); link "Sửa khai báo" → existing
   `/catalog/<code>/edit`; link "Chi tiết" → `/catalog/<code>/detail`.
5. **Nav banner on catalog list** — when total conflict count > 0,
   show a stripe above the table: "X dòng cần review (Y khai báo, Z
   nguồn cung) → Xem trang conflicts". Hidden when count = 0.
6. **Pagination** — same `limit/offset` pattern as the list page;
   default 50/page. Expected volume low (single digits to low
   hundreds per client), but be safe.
7. **Counts header** — page top shows total + per-type breakdown
   (mirrors list page provenance-counts header).
8. **Tests** —
   `tests/test_catalog_conflicts_page.py` provider-level:
   - fixture inserts 2 conflict rows (1 declared, 1 sourcing) + 1
     clean row;
   - assert page renders both conflict rows, omits clean;
   - assert filter `type=declared` shows only declared row;
   - assert filter `type=sourcing` shows only sourcing row;
   - assert counts header shows `2 (1, 1)`;
   - smoke test that nav banner appears on catalog list when count > 0
     and is absent when count = 0.

**Out:**

- **Suppress / ignore mechanism.** Memory `feedback_no_derived_in_source`
  + immutable principle: staff resolve by editing `category_override`
  or `btp_sourcing` to match observed (or by accepting a different
  category as correct). No new `is_suppressed` column. If
  resolve-via-edit proves insufficient in practice, revisit.
- **A.4 cross-source inconsistency warnings** (HS code drift, UoM
  drift, origin drift) — separate scope, already partly shipped in
  detail page. This page only surfaces the 2 conflict signals from
  the catalog data graph itself.
- **Bulk-resolve actions** (apply same action to N selected rows) —
  defer until first staff request signals real need.
- **Schema migration** — none. View + materials already carry every
  needed signal.

## Manual test plan

1. Open dev server `http://127.0.0.1:8754`, log in as `dev`.
2. Pick a client that has known conflicts:
   - Johnson: 1 `declared_observed_conflict` row.
   - Growatt: 1 `sourcing_conflict` row.
3. From the catalog list, confirm the nav banner shows the conflict
   count and links to `/catalog/conflicts`.
4. Open `/clients/<cid>/catalog/conflicts` — verify count header,
   per-row columns, inline actions, both filter chips work.
5. From a conflict row, use the inline `btp_sourcing` dropdown to
   change to the suggested value; refresh — row should disappear
   from the conflicts page.
6. From a conflict row of declared kind, click "Sửa khai báo" → edit
   the `category_override` to match the observed role → save → confirm
   that row leaves the page on next load.

## Done criteria

- 4+ provider tests pass.
- Page renders for both Johnson + Growatt with non-empty conflict
  lists.
- Nav banner appears on catalog list when conflicts > 0 for that
  client and absents when 0 (or hidden).
- 2-3 PNG screenshots committed under `screenshots/`.
- Brief stays as-is post-ship for cross-reference; BACKLOG A.2 moves
  to Shipped section.

## Cross-links

- BACKLOG entry A.2.
- `v_material_roles` view: `db/migrations/046_v_material_roles_dual_source_btp.sql`.
- Existing inline badge wiring: `app/templates/clients/catalog.html`
  (declared `⚠ Xét lại` line 299; sourcing `⚠ Conflict` line 371).
- Existing actions reused: `POST /catalog/<code>/btp_sourcing`,
  `GET /catalog/<code>/edit`, `GET /catalog/<code>/detail`.
