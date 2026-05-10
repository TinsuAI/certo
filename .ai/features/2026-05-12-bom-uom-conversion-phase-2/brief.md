# Feature: BOM UoM conversion engine (Phase 2)

Track D Phase 2. Continuation of `2026-05-11-bom-staleness-track-d/`.
Closes the gap surfaced during Phase 1 real-data test on Johnson
`0000082212`: Refresh button cleared `is_stale` but did not actually
convert UoM (PIECES → KG → PIECES round-trip), because
`materialize_shallow_and_full_flat.py` SQL bypasses the flatten engine.

**Mode:** dev-phase reset path. No backfill. Any major schema/semantic
change → wipe + re-ingest from source XLSX programmatically. Phase 2
must guarantee ingest flow correctness, not upgrade-in-place
compatibility.

**Scope client:** Johnson only for Phase 2 dev/validation. Growatt
deferred — apply same flow once Johnson invariants hold.

## Ingest order + order-independence invariant (NEW — load-bearing)

Canonical ingest sequence per client:

1. **BCCT first** — declarations land. Source of truth for code
   appearance + observed HS / UoM / origin.
2. **Catalog** — two paths:
   - Upload "DS DK HQ" (HQ registration list) if agency provides one.
   - Auto-derived from BCCT: first appearance of each code becomes a
     catalog candidate via `Mã chờ duyệt` flow.
3. **BOM** — programmatic batch script or manual UI upload.
4. **Catalog augmentation** — subsequent BCCT or BOM uploads contribute
   new codes / observations; catalog grows incrementally.

**Hard invariant:** ingest order must not affect final state. Whether
BOM uploads before or after catalog has the code, after BCCT or before,
end state must be byte-identical. Tested via `tests/test_ingest_order_invariance.py`.

Concrete cases derived from invariant:

- BOM uploaded with code X, no catalog row → BOM ingests as raw,
  derived shapes deferred. When catalog later gains X with UoM, derived
  shapes auto-materialize via post-ingest hook re-run.
- BOM uploaded, code X already in catalog with mismatched UoM →
  ingest-time preview surfaces conversion plan; staff confirm; raw
  stored as-is, derived stored converted.
- Catalog UoM edited after BOM derived → mig-053 D7 trigger marks
  derived stale; refresh re-derives with new factor.

## Scope

**In:**

1. **Refresh wires through flatten engine** (BACKLOG sub-task B).
   Replace raw recursive-CTE in `_rederive_shape` with a call into
   `app/flatten/engine.py` so derived shapes inherit canonical UoM
   from `materials.uom` via the existing precedence stack (mig 021 + 051).
2. **Refresh = mint new + supersede old** (BACKLOG Phase 3 F, folded in).
   Different-hash result tombstones the old artifact with
   `tombstone_reason='superseded_by_refresh:<new_id>'`. Same-hash dedup
   still clears flag on the original (no churn for unchanged data).
3. **Ingest-time conversion preview** (BACKLOG sub-task A). Extend
   `compute_uom_drifts` to emit per-row conversion plan: source UoM,
   target UoM, factor, factor source. BOM + BCCT preview UIs render
   the plan; staff actions: confirm-as-shown / edit factor inline /
   skip convert (mark drift flag).
4. **Extend `client_uom_overrides`** (per user decision: merge into
   existing table, no new `material_uom_factors`). Add columns:
   - `is_cross_family boolean` (computed at insert from `from_uom` /
     `to_uom` family lookup; true → mandatory factor).
   - `notes text` (staff annotation).
   - Extend `source` enum to include `supplier_data`, `packaging_spec`,
     `derived_average`, `imported`.
   - Admin UI for browse/edit/add per material × per direction.
5. **Conversion audit trail** (BACKLOG sub-task D). `bom_artifact_rows`
   gains nullable `source_uom text` + `applied_override_id`. Forensics
   for "which factor did this derived row use".
6. **Manual_flat UoM drift signal** (BACKLOG Phase 3 E, folded in).
   `manual_flat_as_provided` artifacts can't be re-derived; surface a
   separate `has_uom_drift boolean` (driven by D7-extended trigger).
   Different badge in UI ("Re-upload BOM" action, not "Refresh").
7. **Order-independence safeguards.** Post-ingest hooks for catalog
   ingest must re-run derive on BOM artifacts that referenced codes
   newly catalog'd. New trigger D9: catalog-row-insert (when
   referenced by existing bom_edges) marks corresponding derived
   artifacts stale → refresh materialises them.
8. **Sister-app notes (thorough — sole handoff mechanism)** at
   `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md`.
   Ship-fast / accept-breakage stance: Data Hub flips behaviour
   without per-client gate; sister apps catch up async on their own
   schedule. Notes must capture enough detail for a cold BCQT or CO
   session to pick up months later without context: behaviour
   before/after, exact API/schema diff, breaking-change impact on
   consumer queries, recommended consumer-side updates, test
   fixtures showing converted vs raw rows.

**Out (defer to Phase 3+):**

- Bulk import factors from supplier sheet (nice-to-have).
- Generalized factor data import API.
- Johnson programmatic bulk re-ingest script
  (`scripts/bulk_reingest_johnson.py`) — separate BACKLOG entry,
  unblocks AFTER this ships.
- Aggregate-data git-history for `client_uom_overrides` edits
  (separate BACKLOG entry).

## Decisions

1. **Storage: extend `client_uom_overrides`, no new table.** Schema
   churn minimised; lookup precedence (mig 021 §4) already correct.
   Cross-family flag added as derived column — `make_uom_lookup`
   learns to treat cross-family rows as mandatory (no canonical
   fallback).
2. **Refresh tombstones old on hash-change.** Aligns with BOM
   immutable principle. Old artifact keeps `is_stale=true` AND gains
   `tombstoned_at` + `tombstone_reason`. Lineage chain preserved via
   existing `parent_artifact_id`.
3. **Refresh same-hash → clear flag without tombstoning.** Common
   case after re-ingest: catalog UoM equals raw UoM → no derived
   change → no churn.
4. **No per-client flag, no compat window.** Dev phase + reset path
   mean Phase 2 ships unconditionally. No
   `auto_convert_uom_at_refresh` toggle.
5. **Conversion target = `materials.uom`.** When NULL, derived shapes
   defer materialisation (post-ingest hook waits) and emit a
   `catalog_uom_missing` audit entry. Don't fall back to raw silently
   — that violates order-independence (BOM-before-catalog vs
   BOM-after-catalog would diverge).
6. **Cross-family handling — 3-tier default policy** (confirmed
   2026-05-12, supersedes blocker-only model):
   - **Tier A (count↔assembly/packaging)**: when both canonical
     families ∈ {`count`, `count_packaging`, `assembly`}, engine
     defaults `factor=1.0` with `source='unconfirmed_default'`.
     Derived artifact marked `has_uom_drift=true` reason
     `unconfirmed_default_1to1`. Yellow UI badge.
   - **Tier B (count↔mass/length/volume)**: NO default. Engine
     returns `uom_conversion_missing` → `has_uom_drift=true` reason
     `factor_missing`. Red UI badge. Hard-block until factor row
     populated.
   - **Tier C (same-family different canonical)**: existing
     `uom_canonical` precedence handles, no change.
   - Confirmation lifecycle: only "real row in
     `client_uom_overrides`" clears the drift badge. No
     "approve-as-is" button — keeps semantics clean.
7. **Manual_flat = source artifact, never re-derive.** Phase 2 adds
   `has_uom_drift` distinct from `is_stale`. UI surface differs:
   "Re-upload BOM" action vs "Refresh".
8. **Order-independence enforced via post-ingest hooks.** Catalog
   inserts that match outstanding BOM-only codes trigger
   re-materialisation. BCCT inserts contribute observed UoM that
   feeds `Mã chờ duyệt` candidate enrichment (existing flow, no Phase
   2 change).

## Risks

- **Cross-family factor data missing at ingest time.** No universal
  factor for `PIECES → KG`; depends on per-material physical
  properties. If staff has not populated `client_uom_overrides`
  before bulk re-ingest, derived shapes for those rows ship with
  `has_uom_drift=true` — visible but not converted. Mitigation:
  inventory step (item 0 below) audits source XLSX for cross-family
  pairs BEFORE re-ingest run; admin UI populates upfront.
- **Order-independence regression.** Hardest invariant to guarantee.
  Mitigation: dedicated test file
  `tests/test_ingest_order_invariance.py` with permutation harness
  (BCCT→Catalog→BOM, BOM→BCCT→Catalog, etc) on a fixture client.
- **Audit columns add storage.** `bom_artifact_rows` gains 2
  nullable columns × N rows. Trivial; defaulted NULL.
- **Catalog-driven re-derive cascade.** Single catalog UoM edit →
  every BOM artifact referencing that code goes stale → refresh-all
  materialises N artifacts. Tested under Johnson scale (246 TP × 3
  shapes ≈ 738 artifacts max). Mig-053 partial index covers
  `is_stale=true`; refresh route already paginates per-product.

## Open Questions

1. **`material_observations.py` workaround.** Phase 2 doesn't touch
   view-time recompute. Verify no regression in `/catalog/<code>/detail`
   after refresh-tombstones-old.
2. **Idempotency boundary on `client_uom_overrides` UPDATE.** If
   staff edits a factor mid-refresh, snapshot at refresh start
   (capture `applied_override_id` before iterating shapes).
3. **Catalog-edit → re-derive scope.** D9 trigger fires when catalog
   `material_code` inserted matching existing `bom_edges.child_code`.
   What about `bom_edges.parent_code`? Edge case: TP root edited.
   Default: include both directions; surface in admin diff before
   bulk refresh.

## Implementation phases (estimate: ~1-1.5 weeks)

Each step its own commit pair (tests + impl):

0. **Source-data audit (DONE).** Johnson source 06.05.2026 audited.
   Output: `factor_inventory.md`. 220 cross-family codes inventoried;
   8 unknown UoM tokens listed; 3 risks surfaced (EA↔SETS dominance,
   EA↔KG/MT physical-weight gap, multi-meaning Vietnamese tokens).
   Growatt deferred.
1. **Mig 055: extend `client_uom_overrides`** — `is_cross_family`,
   `notes`, source enum extension. Backfill `is_cross_family` on
   existing rows. **~0.5d.**
2. **Flatten engine wiring** — `_rederive_shape` calls
   `flatten_engine.flatten()` instead of raw SQL. Tests assert old
   SQL output equals engine output for same-UoM artifacts (no
   regression) AND different output for cross-UoM artifacts
   (conversion happening). **~1.5d.**
3. **Refresh-as-new-artifact** — different-hash mints + tombstones
   old. Update `bom_staleness.refresh_artifact` + tests. **~1d.**
4. **Mig 056: `bom_artifact_rows` audit columns** — `source_uom` +
   `applied_override_id` nullable. **~0.5d.**
5. **Ingest-time preview enhancement** — `compute_uom_drifts` emits
   conversion plan; BOM + BCCT preview UI shows table + 4 actions
   (confirm / edit factor inline / save factor to table / skip).
   Tests. **~3-4d.**
6. **Mig 057: manual_flat drift signal** — `has_uom_drift` column;
   D7-extended trigger; UI badge. **~1d.**
7. **`client_uom_overrides` admin UI** — `/admin/uom-factors` route
   + table + CRUD forms. Reuses `/admin/uom` chrome. **~2d.**
8. **Order-independence harness** —
   `tests/test_ingest_order_invariance.py` permutation tests. D9
   trigger for catalog-insert → BOM-derived re-materialisation.
   **~1.5d.**
9. **Factor table populated** for Johnson cross-family pairs from
   item 0 (220 codes). Includes agency Q&A on EA↔SETS rule + FT/CV
   abbreviations. **~1d staff session via admin UI.** Growatt
   deferred.
10. **Reset + re-ingest dry run** on staging copy. Verify all
    invariants. **~0.5d.**
11. **Sister-app notes + final commit.** **~0.5d.**

## Manual test plan

1. **Order-independence (primary new)**: same client, same source
   data, run 3 permutations of BCCT/Catalog/BOM ingest order.
   Final SQL diff = empty.
2. Johnson `0000082212` end-to-end: PIECES → KG via factor row →
   refresh produces converted derived rows; old artifact tombstoned;
   audit trail shows applied_override_id. **Primary regression.**
3. Johnson sample same-family case (`G` → `KG` in Component unit):
   refresh succeeds via `uom_canonical` family precedence (no
   override needed). Test fixture: any code with `G` in BOM rows.
4. Cross-family without factor row, ack-skip: ingested raw, derived
   shapes get `has_uom_drift`; refresh keeps stale with
   `factor_missing` reason; UI shows "Add factor" action.
5. Manual_flat with catalog UoM mismatch: badge "Có khác biệt UoM
   với danh mục" + "Re-upload BOM" action.
6. Catalog UoM edited after BOM derived: D7 trigger marks stale →
   refresh re-derives with new factor → old tombstoned.
7. BOM uploaded for code not in catalog → catalog later created
   matching code with UoM → D9 trigger fires → derived materialises
   with conversion.
8. Concurrent refresh + factor edit: applied_override_id matches
   refresh-start snapshot.

## Done criteria

- [ ] Mig 055-057 applied; tests green (current baseline 849 → +50~70).
- [ ] Order-independence permutation tests pass.
- [ ] Johnson `0000082212` test case passes end-to-end with conversion.
- [ ] `_rederive_shape` calls flatten engine; raw SQL bypass deleted.
- [ ] Refresh hash-change tombstones old with reason link.
- [ ] BOM + BCCT preview show conversion plan + 4 staff actions.
- [ ] Admin UI for `client_uom_overrides` browse/add/edit/delete.
- [ ] `has_uom_drift` signal + UI badge for manual_flat.
- [ ] D9 catalog-insert trigger drives BOM re-materialisation.
- [ ] Factor table populated for 220 Johnson cross-family pairs.
- [ ] Staging reset + re-ingest dry run clean.
- [ ] Sister-app notes published.
- [ ] Screenshots committed in this feature folder.
- [ ] BACKLOG entry "BOM UoM conversion engine" struck through; F + E
      marked SHIPPED. New BACKLOG entry "Order-independence harness"
      cross-linked.

## Cross-links

- Phase 1: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`
- BACKLOG: "BOM UoM conversion engine (ingest-time + refresh-time)"
- BACKLOG: "Johnson programmatic bulk re-ingest plan" (unblocked by this)
- Memory: `project_uom_drift_gate.md`, `project_bom_staleness.md`,
  `project_bom_immutable_principle.md`, `project_reingest_pending.md`
- Code touchpoints (reading-only):
  `app/flatten/engine.py`, `app/flatten/uom.py`, `app/stores/uom.py`,
  `app/stores/bom_staleness.py`, `app/stores/uom_drift.py`,
  `scripts/materialize_shallow_and_full_flat.py`,
  `app/routes/bom.py:398-422` (preview wire),
  `app/routes/bcct.py:773-789` (preview wire),
  `app/routes/catalog.py` (Mã chờ duyệt + Accept flow — order-independence
  contributor).
