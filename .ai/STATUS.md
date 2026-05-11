# Project Status

**Date:** 2026-05-13 — Shipped mig 063 + canonical-UoM pipeline (3 commits
ahead of `c98527f`). Catalog UoM coverage on Johnson now 13,132 / 13,132
(100%) vs ~24% before. Two known follow-ups queued: SAP parser qty-column
fix + CO consumer migration. Test suite green.

3 commits pending push. Test suite: 1070 passed, 15 skipped.

## Current State

**Branch:** `main`. Working tree clean for code (only untracked are
`docs/training/` + `scripts/generate_training_input_scenarios.py`,
unrelated to this session).

**Tests:** 1070 passed, 15 skipped. Pre-existing failure in
`tests/test_bom_raw_edges.py::test_technical_raw_upload_confirm_materializes_edges`
is unrelated to this session's work (post_ingest_hooks make the old
"1 raw, 0 rows, 2 edges" expectation stale).

**Migrations:** at mig 063 (added this session).

**Dev server:** running on `:8754` with 4 workers, PID 1506476, log
`/tmp/dh_dev.log`. Restart required after code edits.

**Backups:**
- `/tmp/dh_backups/data_hub_pre_johnson_btp_rederive_20260511_1414.dump`
  (243M, pre BTP re-derive)
- `/tmp/dh_backups/data_hub_pre_uom_consolidate_2244.dump` (314M, pre
  mig 063 wipe + re-ingest)

**Johnson catalog state (post-pipeline-fix):**
- TP: 650 / 650 with `uom` (100%)
- BTP: 3,031 / 3,031 (100%)
- NVL: 9,451 / 9,451 (100%)
- All 13,132 codes in `bcct_rows` ∪ `bom_edges` have `materials.uom`
  populated. Pipeline self-heals on re-ingest.

## Recent Changes — this session

**Three commits added** (in order):

1. `6a1b47a feat(catalog): mig 063 consolidate materials.unit → uom`
   — drops legacy `unit` column after one-shot `uom = unit` backfill.

2. `42decc7 feat(catalog): pipeline writes canonical uom at ingest +
   BOM filter/re-root` — every INSERT site writes `uom`; BOM list page
   gets TP/BTP server-side filter; `derive_btp_shallows._subtree_edges`
   re-roots node_path/level + canonical sort fix;
   `materialize_shallow_and_full_flat.materialize_one` now calls
   `_convert_rows_to_catalog_uom` (was refresh-only).

3. `f64b500 test(catalog): invariant tests + uom rename across fixtures`
   — 7 new tests covering UoM capture invariants + rename across 9
   test fixture files.

**Memory entries added (5 total):**
- `project_sap_parser_qty_bug.md` — parser picks `Comp. Qty (CUn)`
  (cumulative) instead of `Component quantity` (per-parent). Fix queued.
- `project_bom_component_unit_canonical.md` — empirical proof
  Component unit is canonical; Base UoM is SAP-internal only.
- `reference_sap_uom_german_defaults.md` — `ST/KAR/ROL/PAA` are SAP
  T006 defaults (Stück/Karton/Rolle/Paar).
- `project_materials_unit_uom_consolidation.md` — mig 063 + grace
  window + sunset date.
- `feedback_check_feature_folder_first.md` — process feedback: grep
  `.ai/features/` before doing audit work (lesson from this session).

## Next Steps

Priority order:

1. **SAP parser qty-column fix** (queued, next session). See memory
   `project_sap_parser_qty_bug.md`. Swap `_QTY_ALIASES` order in
   `app/parsers/bom_adapters/sap_indented_walk.py:37` so
   `"component quantity"` (MENGE = per-parent) wins over
   `"comp. qty (cun)"` (MNGKO = cumulative). Then wipe Johnson BOM +
   re-ingest via `scripts/ingest_technical_raw_batch.py`. Expected:
   BTP `1000534541` collapses from 21 artifacts to ~3 (1 raw + 2 flat).

2. **CO consumer migration** (sister-app, no grace window per user
   decision). Prompt prepared and given to user. CO must update
   `data_hub_client.normalize_material_row` + `normalize_product_row`
   to read `uom` (not `unit`). After CO ships, drop the `m.uom AS unit`
   alias in `app/routes/api.py` + `app/routes/catalog.py` +
   `app/agent/tools.py` (1-liner each). Sunset 2026-05-25 in
   API_CONTRACT is a placeholder; can be sooner once CO ships.

3. **Growatt wipe + re-ingest** (project_reingest_pending.md). Mirror
   Johnson pattern. Now unblocked by Phase 2 UoM convert wiring
   landing in this session.

4. **Vietnamese customs multi-meaning tokens** (Phase 2 follow-up):
   `client_parser_rules` for `Chai/Lọ/Tuýp`, `SOI`, `Thanh/Mảnh/Miếng`,
   `Viên/Hạt`, `Kiện/Hộp/Bao/Gói`. ~0.5d. Inventoried in
   `.ai/features/2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md`.

5. **Push the 3 commits** to `origin/main` when ready. Plus the 1 commit
   pending from prior session (`c98527f` — bcct/by-codes).

## Blockers

- **220-code factor file from Johnson agency.** Already sent
  (`.ai/features/2026-05-12-bom-uom-conversion-phase-2/agency_qa_johnson.xlsx`
  + email draft). Cross-family conversion (EA↔SETS/CAY/KG/MT) blocks
  on agency response. Not a dev blocker per se.

## Notes for Next AI Session

- **Read `.ai/features/` FIRST.** This session wasted ~3-4 turns
  re-auditing Johnson UoM cross-source mismatches that
  `.ai/features/2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md`
  had already covered. Memory `feedback_check_feature_folder_first.md`
  documents the lesson. Default: at session start, `ls .ai/features/`
  and grep for the topic before launching audit work.

- **User prefers direct breaking changes over grace windows for
  sister-app migrations.** When asking to coordinate with CO,
  default to "fix CO directly" rather than "ship Hub with backcompat
  alias + grace period." Grace alias only kept this time because user
  pivoted mid-discussion; future sister-app schema changes should be
  coordinated releases instead.

- **Dev server is running**, healthz returns 200. PID 1506476. If you
  edit code, restart manually (no --reload because --workers 4
  precludes --reload).

- **Parser bug pending fix.** Earlier in this session BTP fragmentation
  on Johnson (`1000534541` had 24 artifacts) was traced to
  `bom_edges.qty_per_parent` carrying cumulative MNGKO values.
  Re-root + canonical sort in `derive_btp_shallows` reduced to 21;
  remaining fragmentation collapses only after parser fix.

- **Materialize_shallow_and_full_flat:** pre-existing bug where
  `create_artifact` always returns artifact_id (so `_inserted` counters
  never decrement) was NOT fixed this session. Cosmetic; doesn't
  affect correctness.

- **CalVer caveat:** today's date is 2026-05-13 per system but some
  prior STATUS.md was dated 2026-05-11; both correct per session-time.
