# Project Status

**Date:** 2026-05-12 — Phase 2 BOM UoM conversion engine **shipped end-to-end**
including UX polish + screenshot smoke verification. 18 commits on `main`,
not pushed.

## Current State

**Branch:** `main`, ahead of `origin/main` by 18 commits, working tree clean.
**Tests:** 952 passed, 15 skipped, 0 fail (baseline 849 → +103).
**Migrations:** at mig 058 applied (59 total).
**Dev server:** running on :8754 (uvicorn auto-reload).

Phase 2 brief at `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`.
9 of 11 brief steps shipped; step 9 agency-blocked, step 10 manual.

| Step | Title | Commit |
|---|---|---|
| 0 | Source data audit (Johnson) | `ee2f551` |
| 1 | Mig 055 extend `client_uom_overrides` | `99953e8` |
| 2 | Refresh converts UoM (3-tier policy) | `fc09725` |
| 3 | Refresh tombstones original on hash diff | `2677cc4` |
| 4 | Mig 056 audit columns | `2ecb6f4` |
| 5 | Ingest preview conversion plan | `c57c627` |
| 6 | Mig 057 manual_flat UoM drift | `04cf077` |
| 7 | Admin UI for `client_uom_overrides` | `29c1a25` |
| 8 | Mig 058 D9 trigger + invariance harness | `2c7f409` |
| 11 | Sister-app cutover notes | `51ec073` |

UX polish + bug fixes on top:
- `e32af44` UX polish (inline edit, XLSX import, template, stale list)
- `e12c68a` Severity drops on override resolve
- `9be707a` Drift UX rollup (button visible, prefill, manual_flat ingest convert)
- `434f7da` Artifact detail drift signal + severity semantic correction
- `1e495d7` **Manual_flat refresh** — re-apply UoM conversion via audit columns
- `0a63c07` Refresh redirects to new artifact + bom_stale text accuracy

Screenshots committed at
`.ai/features/2026-05-12-bom-uom-conversion-phase-2/screenshots/` (11 PNGs
covering full workflow).

## Architecture LOCKED for Phase 2 (don't relitigate)

- **3-tier UoM policy** in `make_uom_lookup`:
  - Tier A (count↔count_packaging↔assembly): default `factor=1.0`
    `source='unconfirmed_default'`. Marks artifact stale.
  - Tier B (mass/length/volume cross): returns None. Hard-block until
    staff populates `client_uom_overrides`.
  - Tier C (same family, different canonical): auto via `uom_canonical`.
- **Refresh = mint new + supersede on hash diff** (immutable principle).
  Same-hash → return existing id, just clear flag.
- **Manual_flat refresh** (round 3): reconstructs originals from
  `source_uom` + `applied_uom_factor` audit columns, re-runs convert.
  No re-upload needed.
- **Catalog UoM source** = `materials.uom` (mig 050+), NOT legacy
  `materials.unit`. `make_catalog_lookup` still uses legacy column —
  different consumers, no cross-cut.
- **`has_uom_drift`** distinct from `is_stale` — applies to source
  artifacts (manual_flat + raw_graph). Cleared by Refresh (manual_flat)
  or re-upload (raw_graph). Mig 057.
- **Convergent state invariant** — D1/D2/D7/D8/D9 triggers + refresh
  chain. Permutation harness `tests/test_ingest_order_invariance.py`.
- **Severity semantic** (round 3 fix): `warn_cross_family` STAYS warn
  even with override row; `resolved_by_override: bool` flag indicates
  whether conversion path exists. UI badge "khác họ ✓" (green) when
  resolved, "khác họ" (red) when blocking.

## Recent Changes — files touched this session

```
NEW migrations:
  db/migrations/055_client_uom_overrides_extension.sql
  db/migrations/056_bom_artifact_rows_uom_audit.sql
  db/migrations/057_manual_flat_uom_drift.sql
  db/migrations/058_d9_catalog_insert_trigger.sql

NEW code:
  app/routes/client_uom_factors.py     (admin UI: list/CRUD/import)
  app/stores/client_uom_overrides.py   (factor management + xlsx)
  app/templates/clients/uom_factors.html (inline edit + prefill)
  app/templates/clients/bom_stale.html (stale list view)
  scripts/screenshot_phase_2_uom.py    (UI smoke harness)

MODIFIED code:
  app/stores/uom.py                    (3-tier policy step 5)
  app/stores/uom_drift.py              (conversion plan + resolved_by_override)
  app/stores/bom.py                    (audit columns insert; loads drift fields)
  app/stores/bom_staleness.py          (manual_flat refresh path)
  app/routes/bom.py                    (manual_flat ingest convert + redirect fix + stale list route)
  app/templates/clients/_uom_drift_banner.html (badge logic + prefill button)
  app/templates/clients/_upload_preview.html (disabled state tooltip)
  app/templates/clients/bom_artifact_detail.html (drift block + Refresh button)
  app/templates/clients/_bom_macros.html (shape badge tooltip)
  app/templates/clients/bom.html (nav links: stale + factors)
  app/i18n.py                          (khác chiều → khác họ)
  app/main.py                          (mount client_uom_factors router)
  app/static/css/app.css               (button:disabled visual)

NEW tests (+103):
  tests/test_client_uom_overrides_extended.py
  tests/test_uom_lookup_three_tier.py
  tests/test_bom_staleness_uom_conversion.py
  tests/test_bom_artifact_rows_uom_audit.py
  tests/test_manual_flat_uom_drift.py
  tests/test_d9_catalog_insert_trigger.py
  tests/test_ingest_order_invariance.py
  tests/test_client_uom_factors_admin.py
  tests/test_uom_drift_conversion_plan.py
  tests/test_manual_flat_refresh.py

NEW docs:
  .ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md
  .ai/features/2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md
  .ai/features/2026-05-12-bom-uom-conversion-phase-2/agency_qa_johnson.xlsx
  .ai/features/2026-05-12-bom-uom-conversion-phase-2/agency_email_draft.md
  .ai/features/2026-05-12-bom-uom-conversion-phase-2/screenshots/*.png (11)
  .ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md

BACKLOG entries added:
  - Unified import UX across all data-import surfaces (~1 week)
  - UI rename "tombstone" → friendly Vietnamese (~4-6h)
  - BOM upload — auto-detect adapter (~1d)
  - Re-evaluate "shallow" shape for manual_flat (~0.5d)
```

## Next Steps

Per backlog priority + Phase 2 unblocks:

1. **Push 18 commits to origin** — user discretion.
2. **Send `agency_qa_johnson.xlsx`** to Johnson (220 cross-family codes
   need factor input). Email draft at `agency_email_draft.md`. Async.
3. **Johnson programmatic bulk re-ingest** — now unblocked by Phase 2.
   Build `scripts/bulk_reingest_johnson.py` per BACKLOG entry.
4. **`v_material_roles` paren-aware** (~1-1.5d) — proper fix for
   `material_observations.py` workaround.
5. **BOM upload auto-detect adapter** (~1d, BACKLOG) — wire
   `parse_with_fallback` so staff doesn't pick parser manually.
6. **4-shape model** for manual_flat (~0.5d, BACKLOG) — distinct shape
   from "shallow". Update `bom_shape()` helper + memory + macro.
7. **Phase 2 catalog `roles[]`** multi-role + drop `category` (~2-3d).

## Blockers

None hard.

Soft (carry-over):
- Johnson factor population needs agency response to ship Phase 2 step 9.
- Sister apps haven't yet adopted Phase 2 schema (sister-app notes
  posted; consumer read may produce different output until they update).

## Notes for Next AI Session

**Read first:**
1. This `STATUS.md`
2. `.ai/sessions/2026-05-12-phase-2-uom-conversion-ship.md` (this session)
3. `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
4. `.ai/features/2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md`
5. `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md`
6. Memory `project_ingest_order_invariance.md` (convergent-state contract)
7. Memory `reference_johnson_source_data.md` (canonical paths)

**Test fixture:** `/mnt/p/Downloads/growatt-uom-drift-test.xlsx` — manual_flat
upload that triggers all 4 drift severities. Generated by inline script
in `scripts/screenshot_phase_2_uom.py::stash_pending` if Downloads file
deleted (use that flow to regenerate).

**Screenshot harness:** `scripts/screenshot_phase_2_uom.py` — runs
end-to-end Playwright walkthrough. Wipes ALL Growatt
client_uom_overrides on each run; restore in caller code if production.

**Known UX gaps (Phase 3+):**
- `compute_uom_drifts` for raw_graph (technical_raw): edges-only model
  — drift detection at upload time still works (against bcct/catalog),
  but no per-edge audit columns. Refresh on raw_graph is no-op (defer
  to derived artifacts).
- `make_catalog_lookup` still queries legacy `materials.unit`; Phase 2
  uses `materials.uom`. Two consumers, two columns. Eventual unification
  is BACKLOG candidate.
- `bom_shape()` maps manual_flat → shallow (memory `project_bom_3_shapes.md`
  3-shape model). User flagged confusing; BACKLOG entry recommends 4-shape.

**User preferences captured this session:**
- Default to "khác họ" not "khác chiều" in Vietnamese UI.
- Inline edit pattern: input fields directly in cell, no toggle.
- Import flow: support BOTH CSV and XLSX, with download template button.
  Storage convention = dynamic generation per feature
  (`render_template_xlsx() -> bytes` in store), not static files. BACKLOG
  for unified import UX across all surfaces.
- Family-difference is invariant; severity must reflect it. Don't fake
  warn → info_family on override.
- Manual_flat refresh expected to retroactively apply factors (round 3
  feedback led to that feature).
- Don't ask user to manually pick parser — auto-detect or error
  (BACKLOG: `parse_with_fallback` integration).

**Demo server (tinsu)** — NOT updated this session. Phase 2 code on
`main` local only.

**Migration state:** at mig 058 applied (59 total).
