# Catalog candidates — filter chips tell the truth and compose (#54)

**Date:** 2026-07-17 · **Issue:** #54 · **Branch:** `fix/nb-two-source-backfill`

## Problem

The page's contract is "the filter IS the rule" (#35): «Duyệt N mã đang lọc»
approves exactly what the filter selects, re-applied server-side. That holds
only if the controls agree with each other. They did not.

**Every facet chip's count was computed in one filter state while its link
navigated to another.** `counts` / `source_counts` / `leaf_count` /
`machinery_total` were all computed over `base` — pending rows with *only* the
machinery filter applied — ignoring `kind`, `source`, `q`, `leaf`,
`min_observed`. The hrefs, meanwhile, preserved some of those. Measured live on
growatt-vn, `?q=001.0033` (2 rows shown):

| chip | claimed | delivered |
|---|---|---|
| NB | **93** | 2 |
| HQ | 17 | 0 (chip should not render) |
| BCCT | 4 | 0 |
| BOM | **73** | 2 |
| BQD | 34 | 0 |

**And navigation silently dropped filters.** Six params (`kind`, `source`, `q`,
`leaf`, `min_observed`, `show_machinery`) lived across three forms that
rehydrated each other with hand-written hidden inputs; each control re-declared
only some of the others. Kind chips carried `q` alone; the search form carried
`kind`+`source` alone; every «✗» link carried `kind` alone.

The sequence that misleads, verified live pre-fix:

1. Tick «Chỉ lá BOM đã làm phẳng» → 2,106 rows, button «Duyệt 2106».
2. Click the **NB** chip to narrow → `leaf=1` discarded → 2,683 rows.
3. Button reads «Duyệt 2683».

A control that means *narrow* returned a **wider** set, and «Tất cả» reported
the filtered count so there was no denominator to notice it by. That button
writes materials in bulk into a table with no delete path that CO reads live.

## Fix

**One owner for filter→URL.** `_filter_params(kw)` is the active filter as URL
params; `_filter_url_builder(client_id, params)` rebuilds any target from the
full state with named facets overridden (`None` drops one). Every chip, clear
link and form target goes through it. Forms emit their hidden inputs by
iterating `filter_params` instead of hand-listing — so a new facet cannot be
forgotten in five places, which is what produced the defect.

**Each facet counted in the state its own click produces.** `_facet_rows(rows,
kw, kind=None)` returns the rows with that facet dropped and the rest applied.
`Tất cả` reads `base_total = len(kind_base)` — the kind facet removed,
everything else kept, which is exactly what clicking it delivers.

### «Tất cả» keeps its non-kind facets — #54's stated expectation withdrawn

#54 said `?leaf=1` should make the chip read 2,704. It still reads 2,106, on
purpose. The chip sits in the kind row, so it drops *kind* and keeps the rest;
clicking it delivers 2,106, so the number is truthful. Making it read 2,704
would mean clearing every facet — which re-introduces **Defect 2's own
mechanism** ("tick leaf → click «Tất cả» → leaf silently discarded → wider"),
differing only in which chip does it. Every clear affordance here is scoped and
labelled («✗ Xóa», «✗ nguồn», «✗ Bỏ lọc»); a full reset would be a new labelled
control, not an overload of a kind chip.

**Accepted cost:** with a rule-bar filter on, the unfiltered total appears
nowhere. #54's "the operator has no denominator" rationale is unmet. There is
no operator — `bom_audit_events` holds one human decision ever against 1,207
script accepts and 0 rejections, and Tier P is not stood up
(`docs/release-engineering.md:116`). Revisit with a real operator or a second
dual-code client: add a passive total to the header or rule bar (a denominator
is information, not navigation) and keep the chip as-is. Amendment recorded on
#54.

## The invariant

> A chip's number is the number of rows you get by clicking it.

Both defects violate it; one property test covers both, at two levels:

- `tests/test_catalog_candidates_filter_state.py` — 6 tests. Reads each chip's
  claimed count, follows its href, counts delivered rows.
- `.ai/features/2026-07-17-catalog-filter-state/ui_smoke.py` — the same
  invariant in a real browser, since HTML-level checks miss `&amp;` decoding.

### Trap worth remembering

Jinja autoescapes `&` → `&amp;` in hrefs. That is correct HTML and browsers
decode it, but `TestClient.get(href)` does not — it parses `?q=X&amp;kind=nb`
as a param named `amp;kind`, silently dropping every param after the first.
The test then passes by coincidence whenever the counts happen to agree, which
is exactly what happened on the first run. `_chips()` now `html.unescape`s.

## Proof

`screenshots/` — `unfiltered.png`, `search.png`, `leaf.png`. The smoke asserts
the invariant per chip per state and exits non-zero on mismatch; it prints
`page 1 of N (paged)` and skips the check where the set exceeds one page.

Run: `uv run python .ai/features/2026-07-17-catalog-filter-state/ui_smoke.py`
(dev server up on :8754).

## Not in scope

Filed as observations, not fixed here:

- Row «Duyệt» is a `<details><summary class="btn-primary">` — a fake button
  expanding a 5-field form inside a table cell.
- "Duyệt" names two different operations side by side: the bulk one derives
  name/category/UoM from data, the row one demands five typed fields.
- "Đề xuất" carries four unrelated meanings in one cell (category,
  multi-direction warning, `bom_role`, leaf-flat).

## Context

Landed alongside #53, which cleared 2,593 corroborated NB codes out of the
queue (2,704 → 111 shown). These defects predate that and outlive it — the page
is the surface for whatever arrives next. Post-#53 a mis-press is bounded at
111 rows rather than 2,704.
