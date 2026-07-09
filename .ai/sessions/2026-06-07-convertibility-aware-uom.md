# Session 2026-06-07 — A.4.4 convertibility-aware UoM divergence

Follow-on to the same-day catalog-detail redesign. Full cycle: backlog
triage → `/discover` → `/tdd` → `/rev` → commit. Result: commit
`50ea6a7` (local, not pushed), full suite 1426 passed / 16 skipped.

## What Was Done

Picked A.4.4 off the backlog after a backlog scan. Built **one** UoM
classifier and rewired the divergence surfaces onto it so that a UoM
difference is only flagged when the units genuinely can't convert.

- **Classifier** (`app/stores/uom.py`):
  - Extracted `resolve_conversion(cur, client_id, material_code, from, to)`
    out of the `make_uom_lookup` closure — the cascade body now takes an
    open cursor and is the single factor authority for both the flatten
    lookup and the classifier.
  - Added `UomRelation` dataclass + `classify_uom_relation(a, b, *,
    client_id, material_code=None)`. Maps `ConversionMatch.source` →
    `{equivalent, convertible, incompatible}` + `confirmed` (False only
    for tier-A `unconfirmed_default`), `factor`, `to_canonical`, `via`,
    `remediation` (`add_factor` vs `add_alias`). Identity short-circuits
    before any DB hit; acceptance is symmetric (tries reverse direction,
    inverts the factor for one-way override rows).
- **Surface 2 — `catalog_bcct_analysis.py`:** `unit` drift classified
  against the dominant (most-frequent) unit; all-convertible →
  `severity=info` + `convertible=True`, any incompatible → stays
  `critical`. Added `convertible` field to `FieldDrift`.
- **Surface 1 — catalog panel:** new `app/stores/catalog_uom_panel.py`
  (`build_uom_panel`) producing 4-state chips; route `catalog.py` rewired
  to call it (dropped the inline `are_equivalent` block); template macro +
  `app.css` 4-state styling; banner switched to `needs_attention` with an
  "✓ quy đổi được" info variant.
- **Surface 3 — ingest gate `uom_drift.py`:** added `relation` /
  `relation_confirmed` derived from `(severity, conversion)` via
  `_relation_from()` (no extra DB call). Left `severity` + `resolved_by_
  override` + `has_blocking_drift` untouched.
- **Surface 5 (discovered) — `catalog_warnings._uom_drift`:** found via
  the verification screenshot (its banner contradicted the new panel).
  Severity now `info` when all convertible-confirmed, `warn` when
  incompatible or tier-A-unconfirmed (matches the panel's threshold).
- **Tests:** +27. New `test_uom_classify.py` (9), `test_catalog_uom_panel.py`
  (6); extended bcct_analysis (4), uom_drift_conversion_plan (relation +
  consistency, later 5 cases), catalog_detail_warnings (3).
- **Artifacts:** brief `.ai/features/2026-06-07-convertibility-aware-uom/
  brief.md`, `ui_smoke.py`, 3 committed screenshots from real Growatt data.

## Decisions Made

- **One classifier, but the BOM-staleness SQL surface stays separate.**
  The "rewire all four onto one classifier" goal can't be literal —
  staleness lives in plpgsql triggers (`has_drift_remaining`). Decided to
  rewire only the 3 Python surfaces (+ the discovered 5th), and treat the
  SQL as a parallel rendering. Backlog **D.2** captures the proper fix:
  replace trigger-push with an input-fingerprint model normalized through
  `classify_uom_relation`. User leaned toward backporting same-family +
  tier-A into the SQL fn but is dissatisfied with the whole staleness
  model — so we deferred the bigger rework instead of patching.
- **Ingest gate keeps family-based severity.** Its acceptance
  (`has_blocking_drift`) was already convertibility-correct; the
  `warn_cross_family` labels are a deliberate family-invariant design with
  pinned tests + rationale comments. Rewriting them would rewrite those
  tests and touch the live upload gate for cosmetic gain. Chose an
  additive `relation` field instead, pinned to the classifier.
- **Tier-A 1:1 = `convertible` + `confirmed=False`, not a 4th relation.**
  UI picks the shade from `(relation, confirmed)`. Keeps the taxonomy at 3
  values while letting the chip render tier-A distinctly (amber "?").
- **Chip = 4 visual states** (user asked me to recommend): equivalent
  (muted) / convertible (teal "→official") / unconfirmed (amber "?") /
  incompatible (red ⚙). Keeps the tier-A guess honest.
- **bcct downgraded drift keeps a quiet note** (user's call), not dropped.

## What Didn't Work / Caught in Review

- **Hot-path regression (Important, fixed):** the `resolve_conversion`
  extraction moved the empty-UoM guard *behind* `connect()`. `convert_qty`
  in the flatten engine reaches `lookup` with an empty `from_uom` (leaf
  row, no unit, catalog has canonical) → a needless connection per such
  row. Restored the early `return None` in the closure before `connect()`.
  Return value unchanged, so tests stayed green — purely perf.
- **Divergence-test gap (Minor, fixed):** the ingest consistency test only
  pinned same-family/tier-A/tier-B. Added `info_alias`→equivalent and
  `info_unknown`→incompatible cases (3→5).

## Open Items

- **D.2 BOM staleness fingerprint rework** — the headline next-session
  item. `has_drift_remaining` still misses same-family `base_factor` +
  tier-A; the real fix is the fingerprint model. Revive
  `.ai/features/2026-05-27-stale-rebuild/`.
- **Dormant ingest `relation` field** — computed but no template consumes
  it yet; `_uom_drift_banner.html` should adopt it.
- **`_uom_drift` parent-edge quirk** — its BOM query (`parent_code OR
  child_code`) conflates a parent's children's units into the material's
  own drift. Pre-existing, out of scope; separate look warranted.
- **Not pushed.** `50ea6a7` is local-only; push + demo deploy if wanted.
- **Repo hygiene** — pre-existing untracked files (sessions, `docs/
  training/`, two `scripts/*.py`) untriaged.
