# Feature: Catalog detail — per-material BCCT time-series

User triggered: after shipping the ad-hoc UoM drift Excel
(`scripts/uom_drift_report.py`) which showed 171/188 Johnson NVL codes
have ≥2 distinct units across 2025–2026, plus 85 with mode-drift and
118 with set-drift between years. The Excel answers "which codes drift"
but doesn't answer the per-code "when did each value change". User
wants the latter as a first-class panel on each material's detail
page.

## Scope

**In:**

1. **New section on `catalog_detail.html`** below the existing snapshot
   drift panel: "Biến động theo thời gian". Collapsed by default;
   expands per-field.
2. **Run-length-encoded (RLE) timeline per categorical field.** For
   each of `unit`, `hs_code`, `origin`, `declaration_type` (the 4
   stable categorical BCCT columns most worth tracking), compute runs
   of consecutive declarations sharing the same value. Each run =
   `(start_date, end_date, value, n_declarations, n_lines, direction_breakdown)`.
   Display as table.

   Example for material `1000469833`:

   ```
   ĐVT (unit) — 3 đoạn
   2025-01-15 → 2025-12-04  SETS    65 tờ khai (NK 65)
   2026-04-02 → 2026-04-09  PIECES  10 tờ khai (NK 10)
   ```

3. **Unit-price aggregate per quarter** as a separate compact panel
   (numeric, not RLE — runs make no sense for continuous values).
   Columns: quarter, n_declarations, min / median / max unit_price,
   currency. Highlights jumps ≥ 2× between consecutive quarters.

4. **Quantity distribution per quarter** in the same numeric panel:
   total quantity declared per quarter, n_declarations, mean qty per
   declaration. Useful for spotting volume shifts.

5. **Inline link from existing snapshot drift rows.** Each drift row
   in the existing panel (`unit/hs_code/goods_name/origin`) gets an
   "Xem biến động →" link that jump-anchors to the matching
   time-series section. Connects the "is there drift?" indicator
   above to the "when + sequence" detail below.

6. **Backed by a new store helper.** Add
   `app/stores/catalog_bcct_timeseries.py::analyze_material_timeline`
   returning a `MaterialTimeline` dataclass: per-field list of `Run`s
   + per-quarter price/qty aggregates. Pure read; computes from
   `hub.bcct_rows` against the existing `(client_id, customs_code)`
   index.

7. **Tests.** `tests/test_catalog_bcct_timeseries.py` — synthetic
   client with 4-5 BCCT rows spread across dates exercising:
   - RLE collapses consecutive same-value rows.
   - RLE splits on value change.
   - Null vs non-null treated as distinct (matches existing snapshot
     panel convention; null displays as "∅").
   - Per-line vs per-declaration aggregation: aggregate per
     declaration_no first to avoid noise from multi-line declarations
     where lines share field values.
   - Quarter aggregation buckets correctly across year boundary.
   - Price-jump highlighting fires when consecutive quarters differ
     ≥ 2×.

**Out:**

- **Goods_name time-series.** Even with RLE, near-duplicate names
  produce useless noise (e.g. `M10x1.5P;G10;OIL` vs `M10x1.5P mm` =
  same product, different formatting). Wait for BACKLOG A.4.3 (smart
  goods_name similarity needs pg_trgm) before tracking name drift over
  time. The existing snapshot panel already surfaces the distinct-name
  count.
- **SVG horizontal timeline visualization.** Defer to phase 2 — MVP
  is table-first. Adds visual polish but no new information.
- **Cross-material comparison.** Already handled by
  `/catalog/conflicts` (shipped 2026-05-15).
- **BOM artifact time-series.** Separate concern — BOM versioning
  already carries lineage. Out of scope here.
- **Excel export per material.** The bulk
  `scripts/uom_drift_report.py` covers the multi-material analyst
  workflow. In-page view is for the per-material drilldown; no
  per-material download button this phase.
- **Editable timeline / staff corrections.** Read-only. The
  underlying BCCT rows are corrected via existing BCCT history UI;
  the timeline re-renders on next page load.

## Decisions

- **RLE over per-declaration rows.** Per-declaration full timeline
  for a 1,037-row code is unreadable. RLE collapses runs of
  consecutive same-value declarations into one row. Empirically
  matches the user's mental model from the Excel report.

- **Aggregate per declaration_no first, then RLE.** Most fields
  (`unit`, `hs_code`, `declaration_type`) are constant across the
  lines of a single declaration; line-level RLE adds noise. Tie-break
  rule when a declaration has multiple distinct line-level values:
  pick the modal value, fall back to alphabetical. Document in store
  helper.

- **Reuse `_FIELDS` definition** from
  `app/stores/catalog_bcct_analysis.py` for consistency between the
  snapshot panel and the time-series panel. Both surface the same
  4 fields with the same severity tiers. Extend with
  `declaration_type` (new — adds the "import scheme changed"
  signal).

- **Time-series and snapshot panel coexist.** Snapshot answers "is
  there drift?" (1-line badge per field with distinct count).
  Time-series answers "when + in what sequence?". Both stay; the
  snapshot links to the time-series.

- **Categorical RLE vs numeric per-quarter aggregate** are two
  different visual shapes — keep them in separate panel sections.
  Don't try to unify into one "timeline" widget.

- **No new migration.** Computed on read against existing
  `hub.bcct_rows`. Memory `feedback_no_derived_in_source` —
  derivable values don't get stored columns. If perf becomes an
  issue, add a materialized view later; not needed at current scale.

- **Date granularity = day.** BCCT `registration_date` is date-typed.
  Aggregation buckets = quarter (calendar quarter Q1/Q2/Q3/Q4 per
  year). Smaller bucket (month) inflates the table without adding
  signal; larger (year) hides the within-year drift the user already
  flagged.

## Risks

- **Performance on big codes.** Distribution check on Johnson:
  - 9,310 distinct customs_codes total.
  - 8,506 (91%) have ≤ 20 BCCT rows → trivial render.
  - 783 (8%) have 21–100 rows.
  - 21 codes (0.2%) have > 100 rows (max 1,037 — the `OTHERS` bucket).
  RLE collapses these into ≤ 5 runs per field in practice. SQL with
  window-function `lag()` on the existing
  `(client_id, customs_code)` index should stay well under 100ms even
  for the 1,037-row case. Add an EXPLAIN ANALYZE check before
  shipping; if any code blows past 200ms, defer worst-offender
  aggregation behind an `?include_timeline=1` query param.

- **Multi-line declarations.** If line-level field values diverge
  within one declaration (rare for `unit`/`hs_code`, more common for
  `goods_name`), the per-declaration aggregation must pick a
  representative. Decision documented above (modal + alphabetical
  tie-break). Worth a test case to lock in.

- **Direction interaction.** Same code as `import` + `export` may
  show different value patterns. Initial implementation: do not
  split by direction (combined timeline). Surface a per-row
  direction breakdown chip (NK 65 / XK 12). If staff feedback says
  the combined view confuses, split into two timelines later.

- **Null vs empty string.** Treat both as `None` upstream; display
  as `∅` (matches existing snapshot panel pattern at
  `catalog_detail.html` line 359).

- **Existing snapshot panel JIT recomputation.** Currently
  `analyze_material_bcct` runs 3 SQL queries on every detail-page
  render. Adding ~5 more for the timeline = ~8 queries total per
  detail render. Acceptable — connection pool handles it, but worth
  measuring against `OTHERS` and the 1,037-row top code.

- **Goods_name noise dragging time-series down.** Deferring per
  decision in "Out" — but if future iteration adds it, A.4.3 noise-
  fold dependency must land first.

## Open Questions

1. **Direction split — combined or split?** MVP combined. If staff
   feedback (Johnson workflow) says they always look at NK and XK
   separately, switch to split. Tag for review post-ship.

2. **Quarter labels — fiscal year or calendar?** Memory
   `feedback_client_specific_in_adapter` + the existing
   `client_config.fiscal_year_start_month` field. Per-client fiscal
   quarter could be more useful for settlement teams. MVP calendar
   quarter; revisit if BCQT consumer needs fiscal alignment.

3. **Should the timeline also surface non-BCCT events** (catalog
   `category_override` changes, BOM artifact creations referencing
   this material, code_mapping changes)? That would turn the panel
   into a true "material biography". Powerful but scope-creeps the
   MVP. Recommendation: ship BCCT-only first; iterate to multi-source
   if user asks. Memory `feedback_check_feature_folder_first`:
   `material_audit_events` (mig 045) already exists for catalog-side
   changes — a future expansion could merge that stream in.

4. **CSV/Excel export of the per-material timeline?** Defer until
   asked. The bulk Excel script already covers the multi-material
   case; the per-material in-page view rarely needs export.

5. **Should the snapshot drift panel hide fields with zero drift?**
   Currently shows "✓ Không có drift" empty state when all 4 fields
   agree. With time-series added, that empty-state message may need
   wording adjustment ("đồng nhất + không có biến động"). Minor copy
   change.

## Implementation Plan

Phase 1 (MVP) — categorical RLE only. ~1 day.

- New store: `app/stores/catalog_bcct_timeseries.py`.
- Wire into `catalog.py` detail route alongside `analyze_material_bcct`.
- Template section: `app/templates/clients/catalog_detail.html`.
- Tests: `tests/test_catalog_bcct_timeseries.py` (~6 cases).

Phase 2 — numeric per-quarter aggregate (unit_price + quantity).
~0.5 day.

- Extend store helper with `QuarterStat` dataclass.
- Add second sub-section to the template.
- 2-3 additional tests for jump-highlighting.

Phase 3 (stretch) — SVG horizontal timeline. ~1 day.

Recommend stop after Phase 1+2 unless staff feedback asks for the
visual. Total commitment ~1.5 days.

## Cross-links

- Existing snapshot drift: `app/stores/catalog_bcct_analysis.py` +
  `catalog_detail.html` lines 286-388.
- Existing BCCT references table: `catalog_detail.html` lines 521-545
  (20 most recent rows). Will sit below the new time-series section.
- BACKLOG A.4 (already shipped 2026-05-10) — this is the natural
  next-iteration of A.4.
- Ad-hoc Excel report: `scripts/uom_drift_report.py` — pattern source.
- Memory: `feedback_no_derived_in_source` (compute on read),
  `feedback_check_feature_folder_first` (no prior brief found).
