# Session: Phase 2 BOM UoM Conversion Engine — Full Ship

**Date:** 2026-05-12
**Branch:** `main`, +18 commits ahead origin
**Tests:** 849 → 952 passed (+103 new), 15 skipped, 0 fail

## What Was Done

Phase 2 of Track D shipped end-to-end. Brief at
`.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md` defined
11 steps; 9 shipped, 2 deferred (step 9 agency-blocked, step 10
manual verification).

### Migrations (4 new)

- **055** extended `client_uom_overrides`: `is_cross_family` BOOLEAN
  (auto-computed via trigger from canonical family lookup) + `notes`
  TEXT + source enum extension (`+supplier_data`, `packaging_spec`,
  `derived_average`, `imported`).
- **056** added UoM audit columns to `bom_artifact_rows`: `source_uom`
  + `applied_uom_factor` + `applied_uom_source` (CHECK constraint enum).
- **057** added `has_uom_drift` + `uom_drift_reasons` JSONB (and
  first/resolved timestamps) to `bom_artifacts` for source artifacts.
  Helper `bom_mark_uom_drift` filters to `manual_flat_as_provided` +
  `no_strategy`. Extended D7 trigger to fire drift on source artifacts
  in addition to derived staleness.
- **058** D9 trigger on `materials INSERT` — closes BOM-before-catalog
  order-independence gap. Marks dependents stale + drift.

### Code

- **3-tier UoM policy** in `app/stores/uom.py::make_uom_lookup`:
  precedence step 5 returns `factor=1.0` `source='unconfirmed_default'`
  for cross-family pairs in {count, count_packaging, assembly} (Tier
  A); returns None for mass/length/volume cross (Tier B); same-family
  auto-converts via `uom_canonical` (Tier C).
- **`_convert_rows_to_catalog_uom`** in `app/stores/bom_staleness.py` —
  reusable convert helper. Emits drift signals (factor_missing,
  unconfirmed_default_1to1, catalog_uom_missing). Captures audit
  columns in row dicts.
- **Refresh-as-supersede**: `refresh_artifact` tombstones original on
  hash diff with `tombstone_reason='superseded_by_refresh:<new_id>'`.
- **Manual_flat refresh path**: `_rederive_manual_flat` reconstructs
  originals from `source_uom` + `applied_uom_factor` audit columns,
  re-runs convert, mints new artifact. parent_artifact_id=None so
  same-hash dedups against the original (lineage via tombstone_reason).
- **Manual_flat ingest convert**: `preview_confirm` route now runs
  convert layer before `create_artifact` for non-technical_raw
  uploads. Source rows store catalog UoM with audit columns.
- **`compute_uom_drifts` enhancement**: emits per-row conversion plan
  (factor + source + would_block) by calling `make_uom_lookup`.
  `resolved_by_override: bool` flag distinguishes "cross-family with
  factor" from "cross-family without factor".
- **`has_blocking_drift`** logic: blocks based on `conversion.would_block`
  not severity alone. Tier-A defaults allow confirm; tier-B without
  override blocks; override row unblocks.
- **`_clear_stale`** clears BOTH is_stale and has_uom_drift columns +
  reasons + resolved_at. Was clearing only is_stale.
- **Refresh route redirect**: redirects to `result.new_artifact_ids[0]`
  when it differs from original (avoid showing tombstoned page after
  supersede).

### UI

- **Admin UI** `/clients/{id}/uom-factors` — list/CRUD/import for
  `client_uom_overrides`. Inline edit pattern: input fields directly
  in cells, save button per row. Cross-family badge auto-computed.
- **CSV + XLSX import** with download template button. Template
  generated on-the-fly via `render_template_xlsx() → bytes` (2-sheet
  workbook: data + Hướng dẫn). Convention: each feature owns its
  template helper; no static files.
- **Prefill flow**: "+ hệ số" button on drift banner links to admin UI
  with `prefill_material_code/from_uom/to_uom` query params. Form
  auto-fills, scrolls into view, focuses on factor input. Highlighted
  border + bg when prefill active.
- **Drift banner** updated: 2 new columns (Hệ số quy đổi + button).
  Severity badges color-coded; resolved-by-override shows "khác họ ✓"
  green badge instead of red warn.
- **Disabled button visual**: CSS rule for opacity 45% + grayscale +
  cursor not-allowed + pointer-events:none. Wrapped initial-disable
  JS in `DOMContentLoaded` (timing fix).
- **Artifact detail**: drift block (red border, parallel to stale block)
  with humanized per-dim text and per-reason "+ hệ số" links. Refresh
  button rendered for manual_flat artifacts (was missing).
- **Stale list view** `/clients/{id}/bom/stale` — all artifacts with
  is_stale OR has_uom_drift. Differentiates derived vs source actions.
- **Shape badge** `_bom_macros.html` — tooltip per shape; `manual_flat`
  shows "shallow (manual_flat)" with explanation.
- **Confirm form** title hint when `uom_drift_blocks_confirm` true.

### Docs + ops artifacts

- `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md` —
  Phase 2 spec, 8 decisions, 11-step implementation plan.
- `factor_inventory.md` — Johnson source audit: 220 cross-family
  codes (176 EA-SETS, 41 EA-CAY, 3 EA-mass), FT/CV system-side, BCCT
  3-pass scan verification.
- `agency_qa_johnson.xlsx` — 4-tab Q&A workbook (instructions + 3
  factor sheets, direction-explicit).
- `agency_email_draft.md` — Vietnamese email + internal notes.
- `screenshots/*.png` — 11 PNG smoke captures of full workflow.
- `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md` — sole
  handoff for BCQT + CO consumer cutover (ship-fast / accept-breakage
  stance).

### BACKLOG additions

- Unified import UX across all data-import surfaces (~1 week, design
  pattern + audit existing surfaces).
- UI rename "tombstone" → friendly Vietnamese (~4-6h, UI only, NOT
  DB columns or code identifiers).
- BOM upload — auto-detect adapter (~1 day, wire `parse_with_fallback`).
- Re-evaluate "shallow" shape for manual_flat (~0.5 day, recommend
  4-shape model with distinct `manual_flat`).

## Decisions Made

1. **3-tier policy adopted** (decision 6 of brief): tier-A defaults to
   1:1 for count↔count_packaging↔assembly; tier-B hard-blocks
   count↔mass; tier-C auto-converts same-family. Empirical signal from
   Johnson source: 4000× spread in EA↔SETS ratios → no global rule
   possible, per-code factor required. Tier-A 1:1 default OK because
   SETS/CAY are often packaging synonyms of EA.

2. **Severity is invariant** (round 3 user feedback): family
   difference is permanent. Override row provides conversion PATH but
   doesn't make families equal. Solution: keep `severity =
   warn_cross_family` always when families differ; add
   `resolved_by_override` flag for UI presentation. Reverted earlier
   "info_family" downgrade because that misrepresented the family
   relationship.

3. **Manual_flat refresh implemented** (round 3 user feedback): user
   pushed back on "source = immutable, can't refresh". Implemented via
   reconstruction from audit columns. Lineage preserved via tombstone
   chain (parent_artifact_id=None on refresh, link via
   tombstone_reason). This deviates from strict "source immutable"
   reading but aligns with user's UX expectation: factor change should
   propagate.

4. **Catalog UoM source** = `materials.uom` (mig 050+), not legacy
   `materials.unit`. Bypassed `make_catalog_lookup` (which uses
   legacy column) by direct query. Two columns coexist; future unify
   in BACKLOG.

5. **Convergent state invariant** redefined per user clarification:
   not just file-order within group — ANY event ordering (file order,
   dependency changes, external context changes) must converge to
   same end state. Test harness rewritten to test cross-group
   permutations + dependency change post-convergence.

6. **Storage convention for templates**: dynamic generation per feature
   (`render_template_xlsx() -> bytes` in store) rather than static
   files. Avoids drift between code + template; each feature owns its
   schema.

7. **Sister-app cutover** = ship-fast, accept-breakage stance per
   round 1 user direction. Detailed sister-app notes for BCQT + CO
   to pick up async.

8. **Per-client flag, preflight script, lock-step coordination**
   dropped early in session per user feedback ("dev phase, reset is
   escape hatch"). Confirmed correct decision after round 3 fixes.

## What Didn't Work

1. **Initial test file `growatt-uom-drift-test.xlsx`** had header
   `qty_per_unit` which the BOM parser doesn't recognize (normalize
   converts underscores to spaces; alias list has `qty per` not
   `qty per unit`). Renamed header to `qty` to match. Lesson: parser
   header matching is **exact normalized match**, not substring.

2. **Severity downgrade `warn_cross_family` → `info_family` on
   override** (round 2). User pushed back: families are still
   different; calling them "cùng họ" is wrong. Replaced with
   `resolved_by_override` flag + UI distinguishes via badge color.

3. **Confirm button initial-disable JS** ran sync at parse time before
   `confirm-form` was in DOM. `getElementById` returned null → return
   early → button never disabled visually. Fixed by wrapping in
   `DOMContentLoaded`.

4. **First convergent-state harness** included 2 conflicting events
   (`catalog_M_X_kg` + `catalog_M_X_to_g`) writing to same field with
   different values. Last-write-wins semantics meant ordering DID
   matter — invalid test design (events not commutative). Replaced
   with post-convergence edit test.

5. **Manual_flat refresh same-hash dedup** failed initially because
   `parent_artifact_id=original_id` differed from original's
   `parent=None`. `create_artifact` dedup checks `(parent_norm, hash)`
   — different parent → no dedup → minted new artifact. Fixed by
   passing `parent_artifact_id=None` for refresh, lineage via
   tombstone_reason.

6. **`_clear_stale` race** with `_apply_drift_to_artifact`: same-hash
   manual_flat refresh applied drift then immediately cleared the
   same artifact's flag. Fixed via `ids_just_got_drift` set check
   before clear.

7. **Refresh route redirect** kept user on tombstoned artifact after
   supersede. Fixed to redirect to `new_artifact_ids[0]` when it
   differs.

## Open Items

1. **Push to origin** — 18 commits ahead, user discretion.
2. **Agency Q&A** — `agency_qa_johnson.xlsx` ready to send. 220
   cross-family codes need Johnson factor input. Async.
3. **Johnson programmatic bulk re-ingest** — now unblocked by Phase 2.
   Build `scripts/bulk_reingest_johnson.py` per BACKLOG entry.
4. **Sister-app coordination** — BCQT + CO read
   `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md` and
   update consumer code on their schedule.
5. **Demo server (tinsu)** not updated; Phase 2 local only.
6. **Raw_graph refresh** — currently no-op for technical_raw artifacts.
   Re-deriving descendants is a separate concept; defer to a Phase 3
   design pass if needed.

## Cross-references

- Brief: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
- Sister-app notes: `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md`
- Migrations: 055, 056, 057, 058
- Memory updated: `project_ingest_order_invariance.md` (clarified scope),
  `reference_johnson_source_data.md` (NEW — canonical repo path).
- Test file: `tests/test_ingest_order_invariance.py` (8 permutation +
  post-convergence tests)
