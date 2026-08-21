# Session: Mẫu 16 ingest + UoM evidence audit (Johnson)

**Date span:** 2026-05-13 → 2026-05-15 (continuous block via /handoff)
**Branch:** `main` — 6 commits, not pushed
**Result:** Mẫu 16/2025 ingested as `manual_flat` artifacts with proper UoM conversion. `/bom/stale` page redesigned with action-oriented tabs. Bulk script ordering documented. Per-material UoM overrides refactored based on BCCT dual-unit evidence (vs initial blanket factor=1.0 assumption that user correctly pushed back on).

## What Was Done

### Mẫu 16/2025 ingest scaffold (commit `69b9da0`)

- Mig 065: `bom_artifacts.human_label TEXT NULL` for UI display ("Mẫu 16/2025" vs "BOM kỹ thuật SAP").
- Mig 066: extended `chk_actor` with `customs_filing`, `chk_intent` with `customs_declared` (round 2 — round 1 mislabeled as `erp_pipeline`/`asserted_technical`, user audit caught it).
- Scripts: `preprocess_mau16_to_xlsx.py` (xls→flat xlsx, 4-col forward-fill, footer skip) + `ingest_mau16_johnson.py` (manual_flat adapter + per-year variant `m16_2025`).
- 517 TP × 42,287 NVL rows ingested. 100% TP + NVL match catalog (zero missing).
- Brief at `.ai/features/2026-05-13-mau16-ingest/brief.md`.

### Stale-page UX redesign (commit `3baea87`)

- Added 3 missing i18n keys (`factor_missing`, `unconfirmed_default_1to1`, `catalog_uom_missing`) + per-dim tooltips + tab labels (VI + EN).
- Route `/clients/{id}/bom/stale` now classifies each row by dim → 3 categories: `dependency` / `btp_bom` / `uom_drift`. Per-row primary action button per category: Refresh / Open UoM admin / Re-upload.
- Template adds tab navigation with counts per category + filter via `?category=...`.
- `materialize_shallow_and_full_flat.py --cleanup-stale` flag added for D2 false-positive recovery + docstring documents correct 4-step ingest order to prevent the issue.

### Bug fixes after user audit round 2 (commit `bb0faf1`)

- **Bug 1**: stale-page UoM action button was prefilling TP `product_code` instead of NVL `material_code` from `stale_reasons[].source_pk`. Route extracts NVL codes from UoM-dim reasons; template uses first NVL + "(+N)" indicator when multiple.
- **Bug 2** (pre-existing latent): `_rederive_shape` (`app/stores/bom_staleness.py`) called `create_artifact` without `bom_variant_id` → refresh silently produced default-variant duplicates next to agency-batch variant. Fixed by threading variant through `_load_artifact` → `commit_refresh` → `_rederive_shape` → `create_artifact`. Regression test `test_refresh_preserves_bom_variant_id` added.

### Bulk materialize UoM conversion (commit `10c2084`)

- `materialize_shallow_and_full_flat.py` predates Phase 2 UoM conversion (mig 056/057): main loop bypassed `_convert_rows_to_catalog_uom`, so tech_flat rows shipped raw UoM. Fix: main loop now calls conversion + applies drift signals; `flatten_method` bumped to `recursive_sql_with_uom_conversion` v2.
- Verified on Johnson: 42,262 tech_flat rows all have `source_uom` populated; 21,029 actually converted (raw != catalog); 2,543 drift signals surface (legitimate gaps).

### Mẫu 16 ingest UoM conversion (commit `b4665f6`)

- Same gap as bulk materialize but in `ingest_mau16_johnson.py` (I wrote it without the conversion call — caught by user audit).
- Fix: import `_convert_rows_to_catalog_uom` + `_apply_drift_to_artifact`; convert per product before `create_artifact`; route drift to `has_uom_drift` (manual_flat is source kind per mig 057).

### UoM evidence audit + per-material refactor (commit `b315eba`)

- After user pushback "có chắc EA=SETS=CAY 1:1 đâu" (correct), audited 3 evidence sources:
  1. BCCT yearly UoM choice — explains 2025→2026 convention shift, doesn't prove factor.
  2. Direct qty comparison tech_flat vs M16 — 65% exact 1:1, 35% NOT (SAP theoretical ≠ M16 declared).
  3. **BCCT dual-unit `(quantity, quantity_2)` mode factor** — strongest evidence. Filter to `(unit, unit_2) = (raw_uom, catalog_uom)`.
- For 87 M16 drift codes:
  - 28 codes mode factor=1.0 → kept override
  - 1 code (`1000454182`) mode factor=2.0 → updated override 1.0 → 2.0
  - 58 codes have only SETS/KG dual-unit (KG = VNACCS tax-weight, not count factor) → DELETED override, M16 ships with Tier-A drift signal
- Kept `chai/ lọ/ tuýp → bottle` alias (pure synonym).
- Brief at `.ai/features/2026-05-15-m16-uom-analysis/brief.md` (174 lines, full methodology + risk + backlog). Lists in `verified_codes.txt` (29) + `unverified_codes.txt` (58).
- Memory entry `feedback_uom_factor_evidence_driven.md` saved for future sessions.

### Data state (Johnson local, end of session)

- 9,928 alive artifacts: 517 m16 + 6,274 tech_flat + 3,137 raws
- 2,543 stale (tech_flat UoM drift, legitimate) + 119 has_uom_drift (M16 58 unverified codes)
- 29 per-material overrides + 1 alias

## Decisions Made

- **`source_bom_kind='manual_flat'`** for Mẫu 16, not new enum. Brief decision 1 — reuse vocab.
- **`bom_variant_id='m16_<year>'`** for annual filing — naturally partitions across `latest_flattened_versions` window function. Avoids post-filter hack proposed in earlier draft.
- **Add `customs_filing` / `customs_declared` to constraint enums** — round 2 of the M16 design. Initial round 1 mislabeled as `erp_pipeline` / `asserted_technical` because those were the only available enum values; user audit caught semantic mismatch.
- **CO 2026 priority handling** — Data Hub returns 409 `dual_source_variants` payload; CO repo handles dropdown + variant pick. NOT a Data Hub responsibility to filter to single answer.
- **`human_label` column** instead of overloading existing `bom_code` (which has SAP semantic) or extending `display_label` template (auto-generated). Per round 1 Q4.
- **Refresh path preserves variant_id** — fix in `_rederive_shape` was pre-existing latent bug. Test added so future regressions caught.
- **Tech_flat stale is the correct signal**, not noise. Direct qty comparison proved SAP ≠ M16 by 35% rows — different concepts (theoretical vs declared). Keep stale flag visible; CO consumer should prefer manual_flat for M16-covered products.
- **Per-material override > client-wide** for UoM rules. Client-wide risks future material being misapplied. Per-material with `notes` audit trail is safer for ops.
- **Evidence-driven, not blanket** — 58 codes without direct BCCT dual-unit evidence got their override DELETED. Acceptable to ship raw VNACCS + drift signal (staff escalates per-code) than silent corrupt 35% of declarations.

## What Didn't Work

- **Round 1: blanket `(SETS, PIECES, 1.0)` client-wide override** (rejected at user audit). My initial instinct was to bulk-confirm 1:1 because BCCT 2025 + M16 + 2026 all consistently used the same UoM choice. User correctly pointed out "consistency of unit choice ≠ consistency of factor". Direct qty comparison revealed 35% non-1:1. Wasted ~2 hours of ingest + re-ingest cycles before pivoting to evidence-based per-material.
- **Round 2: yearly aggregate BCCT 2025 vs 2026 ratio** as factor proxy. Computed `total_qty_2025_SETS / total_qty_2026_PIECES` per material — ratios from 0.5 to 35, all over the map. Conclusion: aggregate totals reflect demand variance year-over-year, not unit factor. Method invalid.
- **Initial actor `'system:ingest_mau16'`** failed `chk_actor` constraint. Had to fall back to `'erp_pipeline'` (also wrong semantically). Round 2 added `customs_filing` enum to fix properly.
- **`--cleanup-stale` first run** unintentionally created variant=default duplicates for 194 products because `_rederive_shape` was losing `bom_variant_id`. Caught by user noticing "VGM0130-05 sao có 2 cái full flat khó hiểu". Fix in commit `bb0faf1`.

## Open Items

- **58 M16 codes**: factor unknown, currently ship raw SETS + Tier-A drift signal. Need Johnson confirmation per-material before they're CO-2026-usable.
- **220 tech_flat codes (EA → SETS/CAY)**: similar story but for SAP-vs-customs convention. Direct qty comparison showed SAP ≠ M16 declared by 35% — these stale signals are arguably correct. CO consumer should prefer manual_flat over tech_flat for M16-covered products. Tech_flat-only fallback (57 products in 2026 XK) need separate analysis.
- **70 products XK 2026 have no BOM at all** — cannot do CO dossier without BOM. Need Johnson contact.
- **Demo box not updated** — still on `fd793fc`. Needs: apply mig 065 + 066, copy `BCDM_TT39 Dinh muc 2025 johnson.xls`, run preprocess + ingest, insert 29 overrides + 1 alias, re-run materialize.
- **Push 6 commits to `origin/main`** — pending user OK.
- **CO repo cross-coordination** — dropdown logic for 409 dual_source must be implemented in CO repo before any Johnson production CO dossier can use the new dual-variant API responses.
- **`derive_btp_shallows` doesn't propagate parent's variant** (separate pre-existing inconsistency observed but not fixed) — BTP raws all mint with variant='default' regardless of parent. Future cleanup.
