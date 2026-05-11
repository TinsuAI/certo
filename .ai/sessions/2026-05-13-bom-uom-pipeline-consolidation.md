# Session 2026-05-13 — BOM/UoM pipeline consolidation (mig 063)

User-driven investigation that started with "tại sao mất hết BOM TP của
Johnson?" and pivoted through five distinct sub-problems before landing
on a schema-level fix. Three commits shipped: `6a1b47a` (mig 063),
`42decc7` (pipeline), `f64b500` (tests).

## What Was Done

### 1. BOM list page TP/BTP filter

`/clients/<c>/bom` defaulted to sort by `n_non_flattened DESC`. BTP
raw_graph fragmentation (1–8 per BTP) pushed 3,031 BTPs to the top,
hiding all 106 Johnson TPs deep in pagination. User reported demo
embarrassment.

Shipped TP/BTP/All chip filter (server-side via `kind=tp|btp`
parameter on `/clients/<c>/bom`). Plumbed through
`list_products_with_bom` + `count_products_with_bom`. Preserves `q`,
`sort`, `dir`, `page`. Verified: all=3137, tp=106, btp=3031.

Files: `app/routes/bom.py`, `app/stores/bom.py`,
`app/templates/clients/bom.html`.

### 2. `derive_btp_shallows` re-root + canonical sort

`_subtree_edges` was setting `node_path=None`, `level=None`,
`sheet_name=None`, `source_row_no=None` for BTP slices. Per user:
"only strip parent-TP path above the BTP, keep below-BTP."

Fix:
- Walk CTE already builds `path` array; plumb it through.
- `node_path` = join of path-from-BTP-root.
- `level` = `len(path) - 1` (BTP root = level 0, direct children = 1).
- `sheet_name` + `source_row_no` still dropped (parent-XLSX-tied,
  would re-fragment dedup).

After first wipe + re-derive: BTP `1000534541` went 24 → 24 (no
change!). Investigated: `normalized_edges_hash` sorts edges by
`(root, parent, child, row_index)` with `row_index` defaulting to 0,
so multi-set-equivalent edges arriving in different order produced
different hashes. Added canonical sort by
`(parent_code, child_code, qty_per_parent, uom)` before return. After
second re-derive: 24 → 21.

Regression test `test_subtree_edges_rerooted_path_and_level` added.

### 3. UoM convert wired into `materialize_one`

Discovered: `bom_staleness._rederive_shape` (refresh path) calls
`_convert_rows_to_catalog_uom` to normalize qty/uom via catalog
canonical. But `materialize_shallow_and_full_flat.materialize_one`
(initial post-ingest path) bypassed it — raw SQL walk only.

Asymmetric behavior: refresh fixed UoM drift, but initial materialize
didn't. Materials uploaded fresh through the standard path landed with
unconverted UoMs. Wired in the same helper. `flatten_method` bumped to
`recursive_sql_with_uom_conversion` v2. Drifts apply via
`_apply_drift_to_artifact`.

### 4. Johnson wipe + re-derive (validation pass 1)

Hard-deleted 3,337 derived BTP raw_graphs + 6,674 derived flatten
shapes (kept the 106 TP raws + 212 TP flats). Re-ran
`derive_btp_shallows_for_artifact` for each TP, then
`_materialize_shapes_hook` to catch up flatten artifacts.

Stats post-re-derive: 3,418 raw + 6,836 flat. UoM aliasing applied to
12,152 / 44,043 rows (~28%). 5,450 derived artifacts flagged
`is_stale` with `catalog_uom_missing`, 106 raw flagged `has_uom_drift`.

### 5. SAP parser qty-column bug discovery

User: "I thought BOM already shows per BTP unit?" Looked at MFW0502-39
XLSX source. Found `Component quantity` (col 10) and `Comp. Qty (CUn)`
(col 11) — two qty columns. The parser's `_QTY_ALIASES` lists
`"comp. qty (cun)"` FIRST, so parser picks the **cumulative-through-
ancestors** column (MNGKO) instead of the **per-immediate-parent**
column (MENGE).

Empirical audit on 106 Johnson files:
- 3,510 / 27,848 rows (12.6%) disagree between the two columns.
- 104 / 106 files affected.
- 0 files missing `Component quantity`. Swap is safe.

Cross-checked with SAP docs (sapdatasheet.org + SAP Community
threads). Confirmed STPOX field semantics: `XMENG`/`MENGE` =
per-parent, `MNGKO`/`MNGLG` = calculated/cumulative.

Fix is 1-line swap, but validation requires full Johnson re-ingest.
**Queued for next session** — see memory `project_sap_parser_qty_bug.md`.

### 6. Cross-source UoM audit (Component vs Base vs BCCT)

User asked: "if we only store Component unit, how do we reconcile
with XNK [BCCT]? XNK uses Base UoM right?"

Tested empirically. 1,296 Johnson materials in both BOM + BCCT:
- 1,060 (82%): BCCT == BOTH Base and Component (no ambiguity).
- 11: BCCT == Component only.
- **0: BCCT == Base only.**
- 224: Cross-family conflict (mostly EA↔SETS).
- 1: Alias gap.

Conclusion: Base UoM is **never** the right column for BCCT
reconciliation. Component unit aligns 100% after `uom_aliases`
normalization. Stored as `project_bom_component_unit_canonical.md`
memory.

### 7. .ai/features/ check — lesson

User pointed out that
`.ai/features/2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md`
already covered the cross-family inventory (220 codes, same
breakdown). Lesson: grep `.ai/features/` BEFORE running audit. Stored
as `feedback_check_feature_folder_first.md`.

Same folder also has `agency_qa_johnson.xlsx` to send Johnson for
per-code SETS→EA factors. Email draft ready.

### 8. Materials `unit` vs `uom` consolidation (the deliverable)

User: "why have 2 columns, just use 1, fix at ingest."

Discovered:
- `hub.materials.unit` (mig 002): auto-bootstrap from BCCT wrote here.
- `hub.materials.uom` (mig 047): Mã chờ duyệt accept flow wrote here.
- Two write paths, two read paths
  (`make_catalog_lookup` reads `unit`,
  `_convert_rows_to_catalog_uom` reads `uom`).
- 76% of Johnson materials had `uom=NULL`.

Discovery into sister apps: CO `data_hub_client.py:592, 606` reads
`unit` field from `/v1/hub/materials` and `/v1/hub/products` JSON.
BCQT not yet wired (declared_materials is local SQLite, not via Hub
API).

### 9. Mig 063 + pipeline ship (commits)

**Commit 1** `6a1b47a` — Migration 063:
- `UPDATE materials SET uom = COALESCE(uom, unit) WHERE uom IS NULL`
- `ALTER TABLE materials DROP COLUMN unit`

**Commit 2** `42decc7` — Pipeline:
- All INSERT sites write `uom`:
  - `provenance.derive_from_bcct`: picks mode(bcct_rows.unit) per code,
    preserves staff-declared uom on conflict.
  - `bootstrap_catalog_from_bcct.py`: rename + COALESCE backfill.
  - `fixup_johnson_btp_sx_after_bom.py`: capture mode(bom_edges.uom)
    for bom_observed BTPs + new 3rd path for leaf orphans
    (child_codes only seen in BOM, default category nvl).
  - `routes/catalog.py` upload INSERT: rename + COALESCE.
  - `bootstrap_btp_roster.py`: post-mig-042 customs_code →
    material_code cleanup folded in.
- Read path: `CatalogEntry.unit → .uom`; `make_catalog_lookup` reads
  `uom`; engine.py uses `cat.uom`.
- API JSON keeps both keys (`m.uom, m.uom AS unit`) for CO grace
  window. `docs/API_CONTRACT.md` sunset 2026-05-25 placeholder.
- Also rolled in: BOM TP/BTP filter, derive_btp_shallows re-root,
  materialize UoM wire-in (from prior tasks in same session).

**Commit 3** `f64b500` — Tests:
- 3 new `test_provenance.py`: derive captures uom from BCCT mode,
  backfills NULL on conflict, preserves staff override.
- 3 new `tests/test_fixup_johnson_btp_uom.py`: BTP mode capture,
  null fallback, no-clobber on existing staff rows.
- 1 new `test_derive_btp_shallows.py`: re-rooted path/level
  regression.
- Fixture renames across 8 test files (`unit` → `uom` kwarg or SQL
  column).

### 10. Validation (post-commit)

Wiped Johnson catalog. Re-ran `bootstrap_catalog_from_bcct.py` →
9,310 codes inserted with `uom` populated. Then rescued 2,615 BTP
orphans (BTP-rooted raw_graphs whose product_code missing from
materials) + 1,207 leaf NVL orphans via inline SQL mirroring the
fixup script. Final state:

**13,132 / 13,132 codes (100%) have `materials.uom`.**

Folded the leaf-orphan rescue into `fixup_johnson_btp_sx_after_bom.py`
as a 3rd path so the pipeline is fully self-contained.

### 11. CO consumer prompt prepared

Drafted handoff prompt for CO repo session. Initial version included
grace-window framing. User pivoted: "skip grace window, ask CO to fix
directly." Rewrote prompt to require direct rename (no
`unit or uom` fallback). Kept Data Hub API alias as-is (user only
wanted the prompt updated, not the code reverted).

## Decisions Made

- **Single canonical column `uom`**, drop `unit`. Reasoning:
  observation tokens preserved at edge/row level
  (`bcct_rows.unit`, `bom_edges.uom`); materials catalog only needs
  ONE canonical for engine consumption. Two write paths with no
  invariant was a class-bug factory.

- **Verbatim backfill in mig 063**: `uom = unit` without alias
  normalization. Alias resolution stays at read time in
  `make_uom_lookup` so changes to `hub.uom_aliases` propagate without
  schema migrations. Same principle as `feedback_no_derived_in_source`
  memory.

- **Mode-based UoM capture at ingest** for both BCCT-observed (mode of
  `bcct_rows.unit`) and bom_observed (mode of `bom_edges.uom`).
  Minority observations don't determine canonical; staff edits
  override via Mã chờ duyệt or material edit form.

- **CO grace window kept** in code (Hub API still emits `m.uom AS unit`
  alias) but user wants CO to migrate directly. Sunset 2026-05-25
  placeholder; actual cleanup will be 1-line revert after CO ships.

- **Parser qty-column fix deferred to next session.** Validation
  requires Johnson wipe + re-ingest, which is a longer cycle than
  fits in this session's scope. Memory documents the fix +
  expected impact.

## What Didn't Work

- **First re-derive of BTP slices (after re-root only).** Expected
  fragmentation collapse from 24 → ~3 artifacts on `1000534541`.
  Got 24 → 24. Root-caused to `normalized_edges_hash` sort order
  (row_index breaks ties when arrival differs). Fixed with explicit
  canonical sort; second re-derive got 24 → 21. Remaining
  fragmentation is real qty differences from the SAP parser bug
  upstream.

- **First materials INSERT-site sweep missed `routes/catalog.py:707`
  upload-via-Excel path.** Found in second grep. Lesson: grep
  `"into hub\.materials"` not just `"INSERT INTO materials"` — case
  variations + SQL formatting matter.

- **First wipe + re-ingest validation** missed leaf orphans (1,207
  NVL codes that appear in `bom_edges` as child but never as parent,
  never in BCCT). Fixup script's parent-only query missed them.
  Added a 3rd insert path in fixup_johnson to cover.

## Open Items

- **Push the 3 commits** to `origin/main`. Plus the prior session's
  `c98527f`. Total 4 commits ahead.

- **CO consumer migration** (sister-app, async). Prompt given to user
  for next CO session.

- **SAP parser qty fix** (`project_sap_parser_qty_bug.md`). 1-line
  swap + test + Johnson wipe-and-replay. Next session.

- **Drop API JSON `unit` alias** after CO migrates. 1-liner each in
  api.py / catalog.py / agent/tools.py.

- **Growatt wipe + re-ingest** unblocked. Mirror Johnson 4-script
  pattern (`project_reingest_pending.md`).

- **Untracked working tree:** `docs/training/` +
  `scripts/generate_training_input_scenarios.py` are unrelated to
  this session and stay untracked.

- **Materialize counter cosmetic bug** (mentioned in STATUS notes):
  `create_artifact` always returns artifact_id even on dedup, so
  `_inserted` increments instead of `_dedup`. Cosmetic in script CLI
  output only; doesn't affect correctness.
