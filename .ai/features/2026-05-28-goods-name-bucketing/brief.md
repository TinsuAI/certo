# Goods-name drift bucketing (catalog detail panel)

Backlog item: **A.4.3 — Smarter goods_name similarity (insignificant-diff folding)**.

## Problem

`app/stores/catalog_bcct_analysis.py` grouped BCCT rows for goods_name
drift by exact-equal value. Real Johnson data has cosmetic variations
per declaration (whitespace runs, double comma, code prefix `<code>#&`,
casing) that each registered as a separate drift value. Staff saw
"4 dòng khác nhau" when there was actually one product described
slightly differently each time.

## Approach

Normalize-then-bucket (deterministic, no extension needed):

- lowercase
- strip leading `<code>#&` prefix (Johnson SAP-export convention)
- collapse any run of whitespace + punctuation to a single space
- trim

`(value, count)` pairs from the SQL group-by are regrouped in Python by
the normalized key. Representative per bucket = highest-count original.
Drift fires only when `bucket_count >= 2`.

## Done criteria

- [x] `_normalize_goods_name()` helper.
- [x] `_bucket_by_normalized()` regroups (value, count) pairs, preserving
  the most-frequent original as representative.
- [x] Wired into `goods_name` drift only (other fields stay strict).
- [x] +4 tests in `tests/test_catalog_bcct_analysis.py`:
  - cosmetic variants bucket to 1 (no drift fires)
  - real semantic divergence still flagged
  - `<code>#&` prefix stripped
  - bucket representative = most frequent original
- [x] Real-data smoke on Johnson top-10 per-product codes: 21% noise
  reduction, zero false collapses.
- [x] Before/after screenshots on `005485-E` (4 → 2 buckets).

## Evidence

Johnson material `005485-E` ("Lò xo bằng thép, lò xo cuộn").

**Before** (`screenshots/before_drift_panel.png`): 4 raw values
differing only by trailing space, code-in-text presence, double space.

**After** (`screenshots/after_drift_panel.png`): 2 buckets — code
mentioned in description or not (the only meaningful difference).

## Out of scope (future improvements)

- Token Jaccard / pg_trgm fuzzy matching for cases like
  `1000492518` (3 different dimension orderings: `119*90mm` vs
  `90x119x58 mm` vs `58x90x119 mm`). pg_trgm extension is already
  available (installed for Feature 4 substitutes); add only if Johnson
  staff still report noise after this lands.
- Trailer stripping (`hàng mới 100%` on 97% of rows, country suffix
  `#&CN` on 10%) — would help only when one row has the suffix and a
  paired row doesn't. Probabilistically small win; add if needed.

## Ship

Commit `d595bbe` — code + tests.
This folder ships the brief + evidence.
