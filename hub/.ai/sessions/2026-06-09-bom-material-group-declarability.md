# Session: BOM Material Group ingest + declarability (R1 + lọc rác)

**Date:** 2026-06-09 · **Branch:** `feat/bom-material-group-declarability`
(6 commits `fba6d63`..`9c59bb8`, **unmerged, unpushed**; mig 078+079 on **local-socket
dev DB only**). Full suite **1456 passed**.

Arc: investigation → implement (mig 078) → CO consumer spec → `/rev` → fix (mig 079)
→ post-fix screenshots → architecture discussion (overfit / pluggability) → handoff.

## What Was Done

**Investigation** (johnson-vn leaf-NVL in BOM but not in BCCT). Found:
- Discriminator is `materials.source` (`bcct_observed` = declarable / has HS; `bom_observed`
  = only-in-BOM / no HS). `hq_registered` is NULL for all johnson → unusable.
- Descriptive names live only in `catalog_candidates.sample_text` (= SAP "Object
  description"); material master `name` = the code; flattened `bom_artifact_rows.payload` was `{}`.
- The SAP source carries **Material Group** (+ Phantom/Bulk) — the deterministic item-type
  key — but `sap_indented_walk.py` parsed then **discarded** it.
- The 1207 bom_observed leaf-NVL are NOT homogeneous: ~drawings/docs/labels (rác) vs
  ~real materials (steel/welding/plastic) unmatched to BCCT. Report:
  `.ai/features/2026-06-08-leaf-nvl-declarability/brief.md`.

**Implementation — mig 078:** raw `material_group` on materials/catalog_candidates/
`bom_artifact_rows.payload`; per-row `excluded_at`/`exclusion_reason`; per-client
`client_material_group_map` (johnson seed); derived view `v_material_classification`
(`customs_relevance` enum). Threaded material_group through parser → `FlattenedRow` →
engine → `version_rows` payload. Gated `exclude_non_declarable` filter (default OFF) on
BOM batch + single-by-id, echoed in `filter_applied`. Materials API + catalog list expose
material_group/item_category/customs_relevance. UI badges: catalog ("Khai báo" col) +
BOM-detail ("Nhóm SAP" + "Bảng kê" cols, dim excluded rows). Backfill script
(`scripts/backfill_johnson_material_group.py`) for existing johnson data. Perf fix
(`50a6bb4`): compute customs_relevance inline (one `v_material_roles` join, was double).

**CO consumer spec:** `.ai/sister-app-notes/2026-06-09-co-consumer-spec-declarability.md`
— rich path: CO swaps its `is_bom_technical_noise` heuristic for DH `customs_relevance`.

**`/rev` → mig 079 (critical fix):** the `/rev` found mig-078 classified by Material
Group ALONE, ignoring import evidence → dropped **205 imported HS-bearing materials**
(incl. steel weight-plates mislabeled RD07). Also RD07 is SAP "Set/Semi-Assy" (mixed
with drawings), NOT "drawing" — mig-078 wrongly excluded ~753 real sets. Fixes:
(1) **import wins** — `has_imports → declarable` before the rác check; (2) RD07
drawing→assembly_set; (3) backfill Phase D rewritten to derive from the view (set +
**CLEAR** stale), import-aware for phantom → idempotent + map/view edits propagate;
(4) parity test (`test_customs_relevance_parity.py`) locks inline(api/catalog) ⇔ view;
(5) bool-parse hardening. Verified: **0 declarable (imported) materials with excluded
rows**; final exclusions = non-imported document/label + phantom only.

**Future-work captured** (for later sessions): BACKLOG A.0 (final sign-off + drawing
auto-hide), B.0 (adapter "module management" admin view + format-variant-as-data), B.0b
(rename material_group → neutral token; generalize map key when 2nd format appears);
DECISIONS 2026-06-09 (extensibility principle).

## Decisions Made

- **`customs_relevance` is a typed enum, not a boolean** — `declarable_unmatched` (real
  material/drawing/set, no import) is KEPT + flagged for review, never auto-dropped.
- **Import evidence wins over the Material-Group heuristic** (the mig-079 lesson). A
  genuinely-imported material is never classified rác.
- **`item_category`/`customs_relevance` are DERIVED (view), not stored** on materials;
  `material_group` raw IS stored (provenance). Inline copies in api/catalog for perf,
  locked to the view by a parity test.
- **Row exclusion is soft (`excluded_at` tag), never DELETE** — BOM-immutable; named
  distinctly from artifact-level tombstone.
- **Serve filter default OFF + per-client rollout** → zero impact on CO/BCQT until opt-in.
- **Architecture principle (DECISIONS 2026-06-09):** core stays format/client-agnostic;
  per-format logic in adapters (existing `BomAdapter` registry), per-client knowledge in
  DATA tables — never `if client_id==`. Declarability = 2 layers (import-evidence
  correctness, general; Material-Group decluttering, optional per-client). **No
  runtime-uploaded `.py` plugins** (RCE/ungoverned — increases chaos).

## What Didn't Work

- **mig-078's blanket Material-Group classification** — ignoring import evidence dropped
  205 real imports; RD07→drawing dropped ~753 real sets. Root cause: trusting the MG map
  without verifying against actual data (RD07 is overloaded). Fixed by mig 079.
- **View-side name-regex for drawing detection** — considered, rejected: ~704 RD07 codes
  have no name in catalog_candidates, so a view join can't classify them. Deferred to
  ingest-time name classification (BACKLOG B.0b).
- **Backfill `UPDATE ... FROM a JOIN v ON ... = r.col`** — Postgres can't reference the
  UPDATE target inside a FROM join; rewrote with implicit comma-join + NOT EXISTS.

## Open Items

1. **Final owner sign-off**, then commit the uncommitted branch bits (`.ai/BACKLOG.md`,
   `.ai/DECISIONS.md`, screenshots 05–08) and **push**. (STATUS.md was intentionally not
   committed — it now holds the later 2026-06-13 outage state; don't clobber it.)
2. **Demo/prod:** apply 078+079 + run backfill (`--apply`, idempotent) only post-sign-off.
3. **CO adoption** in a CO session (the consumer spec). Then flip `exclude_non_declarable`
   for johnson-vn.
4. Deferred: adapter-registry admin view; rename material_group token; precise drawing
   auto-hide. (BACKLOG B.0/B.0b/A.0.)

## Notes

- Dev server up on :8754 (local-socket DB, branch code). Post-fix UI proof: screenshots
  05–08 (01–04 are pre-fix, for before/after).
- Verify queries + test commands are in the conversation + the brief; key check: `select
  count(*) ... where excluded_at is not null and customs_relevance='declarable'` must be 0.
