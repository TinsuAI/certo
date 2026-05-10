# Project Status

**Date:** 2026-05-12 — Phase 2 BOM UoM conversion engine shipped end-to-end.
12 commits on `main` (chưa push). Dev server running on port 8754.

## Current State

**Branch ahead of origin by 12 commits.** Working tree clean.

### Phase 2 — BOM UoM conversion engine (commits `ee2f551..c57c627`)

11 steps planned in brief, 9 shipped + 2 deferred (agency-blocked / manual).

| Step | Title | Commits | Status |
|---|---|---|---|
| 0 | Source data audit (Johnson) | `ee2f551` | ✅ |
| 1 | Mig 055 extend `client_uom_overrides` | `99953e8` | ✅ |
| 2 | Refresh converts UoM (3-tier policy) | `fc09725` | ✅ |
| 3 | Refresh tombstones original on hash diff | `2677cc4` | ✅ |
| 4 | Mig 056 audit columns on `bom_artifact_rows` | `2ecb6f4` | ✅ |
| 5 | Ingest preview surfaces conversion plan | `c57c627` | ✅ |
| 6 | Mig 057 manual_flat UoM drift signal | `04cf077` | ✅ |
| 7 | Admin UI for `client_uom_overrides` | `29c1a25` | ✅ |
| 8 | Mig 058 D9 trigger + invariance harness | `2c7f409` | ✅ |
| 9 | Populate 220 Johnson factors | — | ⏸ blocked on agency response |
| 10 | Staging reset + re-ingest dry run | — | ⏸ manual verification, defer |
| 11 | Sister-app cutover notes | `51ec073` | ✅ |

**Migrations applied:** 055, 056, 057, 058 (4 new, total at 058).

**Test suite:** 849 baseline → **940 passed**, 15 skipped, 0 fail.
+91 tests added across Phase 2.

### Architecture LOCKED for Phase 2 (don't relitigate)

- **3-tier policy in `make_uom_lookup`**: tier-A (count/count_pkg/assembly
  cross → 1:1 default `unconfirmed_default`), tier-B (mass/length/volume
  cross → None, hard-block), tier-C (same-family auto via uom_canonical).
- **Refresh = mint new + supersede old** on hash diff. Same-hash dedup
  just clears flag. Tombstone reason: `superseded_by_refresh:<new_id>`.
- **Catalog UoM source**: `materials.uom` (mig 050+), NOT `materials.unit`
  (legacy column). `make_catalog_lookup` still uses `unit` — different
  consumer, no cross-cut.
- **`has_uom_drift`** column on bom_artifacts — distinct signal from
  `is_stale`, applies to source artifacts (manual_flat + raw_graph),
  cleared by Re-upload BOM, not by Refresh.
- **Convergent state invariant**: same event set in any order → byte-
  identical end state. Mechanism: D1/D2/D7/D8/D9 triggers + refresh.

### Critical pending work

1. **Send `agency_qa_johnson.xlsx`** to Johnson (file at
   `.ai/features/2026-05-12-bom-uom-conversion-phase-2/`). Email draft
   alongside. 220 cross-family codes await factor input.
2. **Push 12 commits** to origin (user discretion).
3. **Sister-app coordination**: BCQT + CO read
   `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md` and update
   their consumer code on their own schedule (ship-fast stance).

## Next Steps

Per BACKLOG.md priority + new Phase 2 unlocks:

1. **Push to origin** (12 commits ahead).
2. **Agency Q&A** for Johnson (send XLSX). Async, doesn't block dev.
3. **Johnson programmatic bulk re-ingest** (`scripts/bulk_reingest_johnson.py`)
   — now unblocked. Build script per BACKLOG entry.
4. **`v_material_roles` paren-aware** (~1-1.5d) — proper fix for
   `material_observations.py` workaround.
5. **Phase 2 catalog `roles[]` multi-role** (~2-3d).

## Blockers

None hard.

Soft:
- Johnson factor population needs agency response to ship Phase 2 step 9.
- Sister apps haven't yet adopted Phase 2 schema (consumer read may break).

## Notes for Next AI Session

**Read first:**
1. This STATUS.md
2. `.ai/sessions/` — session log for 2026-05-12 (TODO: write handoff via /handoff skill)
3. `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md` — Phase 2 scope
4. `.ai/features/2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md` —
   Johnson 220 cross-family + FT/CV system-side resolution
5. `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md` — consumer impact
6. Memory `project_ingest_order_invariance.md` — convergent-state contract

**Memory updated this session:**
- `project_ingest_order_invariance.md` — clarified convergent-state scope
- `reference_johnson_source_data.md` (NEW) — canonical repo path

**Demo server (tinsu)** — NOT updated this session. Phase 2 code on `main`
local only.

**Working-tree state**: clean. 12 commits on `main`:
ee2f551 → 99953e8 → fc09725 → 2677cc4 → 2ecb6f4 → 04cf077 →
2c7f409 → 51ec073 → 29c1a25 → c57c627. Branch ahead origin 12.

**Migration state**: DB at mig 058 applied (59 total).
