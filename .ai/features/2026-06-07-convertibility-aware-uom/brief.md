# Feature: Convertibility-aware UoM divergence

Backlog: A.4.4. Captured 2026-06-07 during catalog-detail redesign.
**Core principle:** a UoM difference is only a *problem* when the two
units are **not convertible**. If a factor exists (same canonical /
same family via `base_factor` / `client_uom_overrides` row), then
BOM≠BCCT and BCCT-row≠BCCT-row are **acceptable** — surface as info,
never as error/block. Reserve warn/block for incompatible pairs with no
factor.

## Scope

**In:**
- New canonical classifier `classify_uom_relation(a, b, *, client_id,
  material_code=None)` → relation + factor + provenance, built on the
  existing 6-tier cascade. No new factor logic.
- Rewire the **3 Python read-surfaces** onto it:
  1. Catalog detail UoM panel (`app/routes/catalog.py:1187-1205`) —
     replace `are_equivalent`-only divergence with 4-state chip
     (equivalent / convertible / convertible-unconfirmed / incompatible).
  2. `catalog_bcct_analysis.py` — `unit` drift no longer hard-coded
     CRITICAL; classify the distinct units, downgrade to info when all
     convertible, keep critical only for genuinely incompatible pairs.
  3. Ingest gate `uom_drift.py` — fold `_classify` family-severity +
     the separate `resolved_by_override` two-step into one relation call.
- Severity rationalization tests across all three surfaces.

**Out (decide — see Open Q1):**
- BOM staleness triggers (`hub.has_drift_remaining`, mig 069/071) are
  **plpgsql** — a Python classifier can't run in-trigger. Treated as the
  reference model, not rewired. Optional small SQL parity backport noted
  below.
- No new migration expected (classifier is pure compute over existing
  tables). UI chip CSS only.

## The engine (already exists — reuse, don't reinvent)

`app/stores/uom.py::make_uom_lookup(client_id)` returns a closure
`(material_code, from, to) -> ConversionMatch | None` implementing the
precedence stack. `ConversionMatch.source` is the discriminator we map
from:

| `source` | relation | `via` | confirmed |
|---|---|---|---|
| `alias` (same canonical, f=1.0) | equivalent | alias | ✓ |
| `global` (same-family base_factor) | convertible | same_family_base_factor | ✓ |
| `client_specific` / `client_wide` | convertible | client_override | ✓ |
| `unconfirmed_default` (tier-A 1:1) | convertible | tier_a_default | **✗** |
| `None` | incompatible | — | — |

`a == b` after normalize short-circuits to equivalent before any lookup.

## Decisions

1. **Extract `resolve_conversion(cur, client_id, material_code, from, to)
   -> ConversionMatch | None`** — pull the cascade body out of the
   `make_uom_lookup` closure into a module-level fn that takes an open
   cursor. The closure keeps its signature (flatten engine's `UomLookup`
   type is unchanged) and just calls it; `classify_uom_relation` also
   calls it. One factor authority, two callers. This is the DRY move that
   satisfies "do NOT reinvent factor logic."

2. **Relation taxonomy = 3 values + `confirmed` flag**, not 4. Brief asks
   for {equivalent, convertible, incompatible} *and* a distinct shade for
   tier-A. Model tier-A as `relation=convertible, confirmed=False` rather
   than a 4th enum — UI picks the shade from `(relation, confirmed)`.
   Result shape: `{relation, factor: Decimal|None, to_canonical: str|None,
   via, confirmed: bool, remediation: 'add_factor'|'add_alias'|None}`.

3. **Symmetric acceptance, directional factor.** Overrides are
   directional (PK `from_uom,to_uom`); alias/same-family invert cleanly.
   Classifier tries `resolve_conversion(a→b)`, then `(b→a)` if None;
   reports the factor for the direction found + which canonical it
   normalizes to. Acceptance verdict is symmetric.

4. **One connection per classify call site, batch on the cursor.** The
   read-surfaces classify a small set of pairs (catalog panel: distinct
   BCCT+BOM units for 1 code; bcct_analysis: distinct units for 1 code).
   Open one `connect()` and pass the cursor to `resolve_conversion` for
   every pair — avoids the closure's per-call connect. Do **not** adopt
   classify on list-views (hundreds of codes) without the cache-first
   fast path (Risk R5).

5. **Unknown-alias remediation differs from missing-factor.** When either
   side has no canonical → `incompatible, remediation='add_alias'` (link
   `/admin/uom`). When both canonical, cross-family, no override →
   `incompatible, remediation='add_factor'` (link `/uom-factors`). The
   ingest gate already splits `info_unknown` vs cross-family; preserve it.

6. **bcct_analysis anchor = most-frequent unit.** Classify each distinct
   unit against the dominant (highest-count) one; O(N), N tiny. All
   convertible/equivalent → severity `info` ("quy đổi được ×N"); any
   incompatible-vs-dominant → severity stays `critical`, message scoped to
   the offending value(s). Matches "100 PCS + 14 SETS = two valid habits,
   not an inconsistency."

## Risks

- **R1 — tier-A 1:1 must never read as silently OK.** It's an *assumption*
  (`unconfirmed_default`). `confirmed=False` must drive a visually
  distinct "cần xác nhận" state, not the plain convertible shade.
  Downgrading it to invisible would hide a real guess.
- **R2 — Python/SQL spec drift.** `classify_uom_relation` (Python, 3
  surfaces) and `hub.has_drift_remaining` (SQL, staleness) are two
  renderings of one rule. They already disagree: the SQL fn only knows
  alias-align + exact override — it **misses same-family base_factor and
  tier-A**, so it over-flags `m` vs `cm` (no override) as drift. Mitigate
  with a shared test corpus asserting both give the same verdict on a
  fixed pair set; optionally backport the two missing cases into the SQL
  fn (small: add a `uom_canonical` same-family join + tier-A family
  check).
- **R3 — severity downgrade is the whole point and the whole danger.**
  A classifier false-"convertible" turns a real CRITICAL into a silent
  info. Test the incompatible cases (count↔mass, mass↔length) hard;
  default unknown/ambiguous to incompatible (conservative).
- **R4 — cache coherence.** `uom_standards` caches alias/canonical
  in-process (needs `clear_cache()` on alias edits); `client_uom_overrides`
  is read live (no cache) so factor edits reflect immediately. classify
  inherits both behaviors via `resolve_conversion`. No change, just note.
- **R5 — list-view perf.** Per-pair DB hit is fine at 1-code cardinality,
  not at list scale. If a list surface ever wants this, add a cache-first
  path: equivalent / same-family / tier-A are client-independent and
  answerable from the cached canonical layer; only cross-family pairs need
  the per-client override DB check (the only tier that can *upgrade*
  incompatible→convertible).

## Resolved (2026-06-07)

1. **BOM staleness SQL — out of scope for A.4.4.** Do **not** pile more
   special-case SQL into the triggers (the user is already unhappy with
   the trigger-push model; a parity backport adds to the thing they want
   gone). Ship the 3 Python surfaces here. The staleness model gets its
   own rework item where `classify_uom_relation` becomes the normalizer —
   see "BOM staleness — rework direction" below.
2. **Catalog chip = 4 states** (recommended): equivalent (muted/no-chip),
   convertible-confirmed (info, "quy đổi ×N"), convertible-unconfirmed
   tier-A (amber "cần xác nhận"), incompatible (warn → `/uom-factors` or
   `/admin/uom`). Keeps the tier-A 1:1 *assumption* visually honest (R1).
3. **bcct_analysis downgraded drift = quiet "đã quy đổi" note.** When
   `unit` drift is all-convertible, keep a low-key info line (units differ
   but convert cleanly), don't drop the row — preserves data visibility
   without the alarm.

## BOM staleness — rework direction (separate item, NOT A.4.4)

The current model is **trigger-push + binary flag**: D1–D9 plpgsql
triggers set `is_stale`/`has_uom_drift` whenever a source row changes.
Two structural problems:

- **Whack-a-mole false positives.** Every benign source edit re-flags
  artifacts; mig 069/070/071 were three successive narrowings of the same
  leak. New special-cases beget the next migration.
- **The flag conflates "an input changed" with "the output is now wrong."**
  A convertible UoM change doesn't make the published `full_flat` wrong —
  flatten already converts at materialize time. So `is_stale` over-warns.

**Proposed model — input fingerprint, derive-on-read:**
- At materialize time, store an `input_fingerprint` on the artifact: a
  hash over the *normalized* contributing inputs (each component's
  **canonical UoM + resolved factor** — via `classify_uom_relation` — plus
  category/sourcing). Not the raw uom string.
- Staleness = `current_fingerprint(artifact) != stored_fingerprint`,
  computed on read (or a cheap periodic job), not by N eager triggers.
- Because the fingerprint stores the *relation-normalized* form, an
  alias/same-family/override/tier-A change produces the **same** hash →
  no false staleness. Only an *incompatible* change, or a **factor change
  that alters the math**, flips it. This subsumes mig 069/071's
  special-casing into one general mechanism and retires the trigger zoo.
- `classify_uom_relation` (this feature) is the keystone primitive that
  makes the fingerprint benign-change-immune — which is why A.4.4 should
  ship first, then the staleness rework builds on it.
- Migration path is incremental: add `input_fingerprint` column, backfill
  from current state, run the derive-on-read check alongside the existing
  flag, compare, then drop the triggers once parity holds. Not big-bang.

File as a Track D Phase 3 item; revive the never-written
`.ai/features/2026-05-27-stale-rebuild/` brief under this direction.

## Implemented (2026-06-07, /tdd)

Classifier + all read-surfaces shipped test-first; full suite 1426 passed.

- **Classifier** — `resolve_conversion(cur, …)` extracted from the
  `make_uom_lookup` closure (single factor authority); `UomRelation` +
  `classify_uom_relation` in `app/stores/uom.py`. 9 tests
  (`test_uom_classify.py`), 16 `make_uom_lookup` regression tests still
  green.
- **Surface 2 — bcct_analysis** — `unit` drift classified vs the dominant
  unit; all-convertible → `info` + `convertible=True`, any incompatible →
  stays `critical`. 4 tests.
- **Surface 3 — ingest gate** — additive `relation`/`relation_confirmed`
  derived from `(severity, conversion)` (zero extra DB), pinned to the
  classifier by a consistency test. Family-based `severity` + the proven
  `has_blocking_drift` left intact (its acceptance was already correct). 2
  tests. **Open**: severity-label relabel of the banner is a deliberate
  family-invariant design; left as-is (see Resolved #1 reasoning).
- **Surface 1 — catalog panel** — `build_uom_panel`
  (`catalog_uom_panel.py`) 4-state chips; route + template + CSS + banner
  rewired. 6 tests. Screenshots in `screenshots/` (equivalent/unconfirmed,
  equivalent/incompatible, alias-equivalent).
- **Surface 5 (discovered) — `catalog_warnings._uom_drift`** — was a 5th
  divergence surface the brief under-counted; over-flagged by
  canonical-count. Folded in: severity now `info` when all convertible-
  confirmed, `warn` when incompatible OR tier-A-unconfirmed (matches the
  panel's `needs_attention`). 3 tests.

## Follow-ups (not done)

- `catalog_warnings._uom_drift` BOM query matches `parent_code OR
  child_code`, so for a code used as a BOM *parent* it also pulls its
  children's units into the drift set (panel uses component-only). This
  conflates "this material's UoM drift" with "this BOM's internal unit
  mix" — pre-existing, out of A.4.4 scope. Worth a separate look.
- BOM staleness SQL parity (`has_drift_remaining` misses same-family +
  tier-A) → folded into the D.2 staleness-rework item, next session.
