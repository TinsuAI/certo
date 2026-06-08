# Feature: BOM staleness — align UoM drift check with the classifier (D.2)

Backlog: D.2. **Scope decided 2026-06-08 after a critic review of the
original fingerprint-rebuild design (below): ship the NARROW fix (A);
defer the full rebuild (B).**

A.4.4 (2026-06-07) built `classify_uom_relation` — the one authority on
"is this UoM difference OK?". The read surfaces adopted it; the **SQL
staleness check `hub.has_drift_remaining` (mig 071) did not**, so it still
over-flags convertible pairs as drift. This feature closes that gap.

## Problem

The trigger leak (mig 069→070→071, three narrowings of one bug) is a
**UoM false-positive** problem: `has_drift_remaining` flags artifacts as
stale/drift when the BOM uom and catalog uom *differ but convert cleanly*.
A.4.4 R2 scoped the fix and we now execute it.

`has_drift_remaining` currently returns "drift remains" (true) unless the
pair is **alias-aligned** (`is_uom_aligned`) or has an **exact per-material
override row** (`from_uom=bom_uom, to_uom=cat_uom`). It misses every other
case `classify_uom_relation` accepts:

| Acceptance case (classifier) | SQL `has_drift_remaining` today |
|---|---|
| identity / alias (same canonical) | ✓ via `is_uom_aligned` |
| per-material exact override | ✓ |
| **same-family `base_factor`** (m↔cm, g↔kg) | ✗ flags as drift |
| **tier-A default** (count/count_packaging/assembly ↔ 1:1) | ✗ flags as drift |
| **client-wide override** (`material_code_key=''`) | ✗ only checks per-material |
| **reverse direction** (override exists `cat→bom`, not `bom→cat`) | ✗ only one direction |

These four misses are the residual false-positives mig 070/071 chased by
hand. The classifier already encodes the correct acceptance; the SQL must
mirror it.

## Scope (A — the narrow fix)

**In:**
1. **Extend `hub.has_drift_remaining`** (new migration) so it returns
   `false` (no unresolved drift) for *all* cases the classifier accepts:
   - same-family `base_factor`: resolve both uoms → canonical via
     `uom_aliases`, then `uom_canonical.family` equality (mirrors
     `_canonical_lookup` step 4).
   - tier-A: both canonical families ∈ `{count, count_packaging,
     assembly}` (mirrors `_TIER_A_FAMILIES`, step 5).
   - client-wide override: also match `material_code_key=''`.
   - reverse direction: accept an override row in either direction.
   - tier-B (count↔mass, mass↔length, no factor) stays drift — correct.
2. **Backfill** — re-run the mig 070/071-style "every row resolved? →
   clear" pass with the widened check, clearing residual false-positive
   `is_stale` / `has_uom_drift` flags. One-shot UPDATE, idempotent.
3. **Parity test** — a shared corpus asserting SQL `has_drift_remaining`
   agrees with `classify_uom_relation` (`relation != 'incompatible'`) on a
   fixed pair set (alias, same-family, tier-A, tier-B, override both
   directions, client-wide, unknown token). This is the **drift guard**
   (A.4.4 R2) — the one mechanism that keeps the two renderings of the rule
   from diverging again. Mirror, then pin.
4. Targeted tests: each newly-accepted case no longer marks stale on a
   catalog-uom edit; tier-B still does.

**Out (explicit):**
- **The fingerprint rebuild (B).** Deferred — see below + critic verdict.
- **Chỗ 2 — CO/BCQT reconcile BCCT per-shipment.** Out (user, 2026-06-08).
  D.2 is BOM-internal flatten staleness only.
- No schema change to `bom_artifacts`. No new columns. Triggers stay as the
  DB-level guarantee. API/UI/`state` column all unchanged.

## Decisions

1. **Mirror the cascade in plpgsql, do NOT call Python from the trigger.**
   `has_drift_remaining` is `STABLE` plpgsql; triggers can't run the Python
   classifier (no plpython3u, and we don't want it — see A.5). Re-implement
   the same-family + tier-A acceptance in SQL and pin it to the Python
   classifier with the parity corpus (Decision-3 above). Bounded, ~one
   `uom_canonical` join + a family-set check — exactly A.4.4 R2's estimate.
2. **tier-A → "no unresolved drift" for the trigger, but the
   `unconfirmed_default_1to1` needs-input signal still comes from
   materialize time** (`_apply_drift_to_artifact`), not from
   `has_drift_remaining`. So widening the SQL must NOT erase the
   "cần xác nhận" surface — verify in TDD that a tier-A artifact still
   reports `needs_input` via its materialize-time reason while no longer
   being re-flagged `needs_refresh` on every benign catalog edit.

## Risks (A)

- **R1 — SQL/Python drift recurs.** Re-implementing acceptance in plpgsql
  is a second rendering of the rule (the exact thing that leaked before).
  Mitigation is non-optional: the parity test (corpus) is the deliverable
  that makes this safe, not a nice-to-have. If it's flaky or partial, A is
  not done.
- **R2 — tier-A needs-input regression.** Widening risks silencing the
  "cần xác nhận" surface for tier-A (R2 above). Test both: not
  `needs_refresh`, still `needs_input`.
- **R3 — backfill over-clears.** The widened check must clear only pairs
  that genuinely convert; a bug here clears a real tier-B drift. Backfill
  uses the same per-artifact "all rows resolved?" gate as mig 070/071 — keep
  that structure, only swap the predicate.

## Deferred: B — input-fingerprint rebuild (NOT this feature)

The original brief proposed replacing all 9 triggers with a stored
`input_fingerprint` + Python `recompute_staleness`. A critic review
(2026-06-08) flagged it as **over-built in the wrong direction**; verified
against code. Kept here as a future direction, gated on these being
resolved first:

- **No family-canonical normalizer exists.** `uom.py` resolves only
  *pairwise* (`resolve_conversion`); the fingerprint needs a single-arg
  "normalize qty to family base" over `uom_canonical.base_factor` — a new
  primitive, not a reuse. The existing re-derive path converts to *catalog*
  uom (the catalog-relative number the fingerprint must avoid).
- **Guarantee downgrade.** Triggers observe *every* write (psql, scripts,
  bulk re-ingest — a documented workflow). App-hook + Python recompute
  leaves staleness silently wrong on bypass paths until a cron that
  **doesn't exist** (mig 062 `background_jobs` is a UI subprocess tracker,
  not a scheduler). For a TT 39/2018 compliance product feeding CO/BCQT,
  under-flagging is a worse failure class than the triggers' over-flagging.
- **Fan-out cost.** `reconcile_for_material` already caps at 50 and reports
  `deferred` — sync full-tree re-derive doesn't scale; B needs a real job
  queue first.
- **Float-hash instability** (`normalized_hash` rounds `float`) and the
  **unknown-token sentinel** (adding an alias would flip the hash — a NEW
  false positive) must be solved before B is correct.

**If B is ever revived**, the critic's recommended shape is the hybrid: a
thin trigger that only stamps `fingerprint_dirty=true` (keeps universal
cheap write-observation) + a worker that computes the verdict off the write
path (all-Decimal quantized arithmetic, stable unknown-token rule,
backfill that preserves rather than erases genuine staleness). Revisit when
a job queue exists or when the conceptual trigger-push model causes real
(not aesthetic) maintenance pain.

## Implemented (2026-06-08, /tdd)

Shipped test-first; full suite **1447 passed / 16 skipped**.

- **Mig 077** (`077_drift_remaining_classifier_parity.sql`) — `create or
  replace hub.has_drift_remaining` widened to mirror the classifier: alias
  (`is_uom_aligned`) + override (per-material OR client-wide, EITHER
  direction) + same-family `base_factor` + tier-A `{count, count_packaging,
  assembly}` all return `false`; tier-B + unknown token return `true`. D7/D9
  triggers call it by name → pick up the new body, no trigger edits. Backfill
  re-runs the mig 070/071 "all rows resolved? → clear" pass with the widened
  predicate (raw / manual_flat / derived clears).
- **Parity guard** (`tests/test_has_drift_remaining_parity.py`, 12 cases) —
  asserts SQL `has_drift_remaining` ⇔ `classify_uom_relation` across alias /
  same-family / tier-A / tier-B / override-both-directions / client-wide /
  unknown-token, each pinned to an absolute expected value (R1 drift guard).
  Wrote failing first: 6 cases red against the old SQL.
- **Trigger regressions** (in `test_bom_state_and_conditional_triggers.py`) —
  D7 skips flag on same-family + tier-A catalog edits; reconcile clears a
  same-family false positive; **tier-A needs-input preserved** (Decision 2:
  the artifact still reports `needs_input` from its materialize-time reason
  even though the widened drift check calls the pair convertible — staleness
  and resolution-quality are decoupled).
- **Behavior-change fallout, accepted** (user 2026-06-08): a CONVERTIBLE
  catalog edit (kg→g) no longer re-derives published rows — they stay in
  their original unit (physically identical, self-describing). Updated
  `test_convertible_context_change_does_not_churn_published_rows` (was
  `..._propagates`); retargeted two D9 tests to incompatible (kg↔ea) pairs so
  they still exercise a genuine drift. Order-invariance: byte-identity for
  uploads, physical-equivalence for convertible edits — noted in
  `project_ingest_order_invariance` memory.

## Next step

`/rev` (risky change: schema fn + staleness semantics), then commit.
