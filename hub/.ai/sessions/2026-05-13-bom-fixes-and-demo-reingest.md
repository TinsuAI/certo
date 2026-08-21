# Session 2026-05-13 — BOM data-quality fixes + CI repair + Johnson on demo

Single continuous session (started 2026-05-12, extended into 2026-05-13)
that spanned five pieces of work in sequence: SAP parser qty-column
fix → BTP subtree dedup → CI pgvector unblock → demo deploy →
Johnson rebuild on demo. Four commits to `main` + one merged PR #1.

## What Was Done

### 1. SAP indented parser qty-column fix — commit `9d1984f`

Discovered + fixed per memory `project_sap_parser_qty_bug.md`. The bug:
`_QTY_ALIASES` in `app/parsers/bom_adapters/sap_indented_walk.py:37`
listed `"comp. qty (cun)"` (MNGKO = cumulative through ancestor chain)
before `"component quantity"` (MENGE = per-immediate-parent). Result:
`bom_edges.qty_per_parent` carried ancestor-multiplier-contaminated
values for 3,510/27,848 (12.6%) Johnson rows, 104/106 files affected.

Followed `/tdd`: red test first
(`test_sap_indented_raw_parser_picks_per_parent_qty_over_cumulative` +
walk-adapter twin) confirmed `qty_per_parent=10` vs expected `5` with
2-column fixture. Green: swapped alias order so MENGE wins. Both
parsers share the alias list (raw-edges path + WebUI walk adapter) →
single fix covers both surfaces.

Validation: wiped Johnson BOM locally (backup
`/tmp/dh_backups/data_hub_pre_qty_fix_20260512_003330.dump`) → bulk
ingest 106/106 → post-ingest hooks 106/106 ok. BTP `1000534541`
collapsed **21 → 9** (3 raw + 6 flat). Parser fix alone wasn't enough
to reach the predicted 3.

### 2. `_subtree_edges` dedup — commit `7552c64`

Investigation of remaining BTP fragmentation showed 3 distinct raws
with 6/4/2 edges respectively. Source XLSX dump revealed BTP
`1000534541` appears 1×/2×/3× across different parent TPs; the
recursive CTE in `scripts/derive_btp_shallows.py::_subtree_edges`
used `UNION ALL` and emitted N copies of each unique `(parent, child,
qty, uom)` tuple — fragmenting `normalized_edges_hash` across TPs.

Red test (`test_subtree_edges_dedups_multi_position_occurrences`)
inserted 2 extra `bom_edges` rows duplicating BTP_INNER2's children,
asserted unique-count match. Green: collect into
`dict[tuple, dict]` before canonical sort.

Validation: re-derived Johnson BTPs only (kept 106 TP raws) → BTP
`1000534541` **9 → 3** ✓ (matched the local-prediction in memory).
Top BTPs all `raws=1`. Total artifacts 10,254 → 9,411 (~8%↓);
edges 77,487 → 64,338 (~17%↓).

Cross-validation extracted OLD full_flat from backup, compared to NEW
on 10 sample TPs:
- VGM-series (deep trees, multi-position): 17-29% leaves changed,
  max ratio **4535×** (one code: 589,712 → 130 EA).
- MFW-series (shallower): 5-11% changed, max ratio 2-32×.
- All deltas are reductions (NEW ≤ OLD). Structure unchanged (no
  codes appeared/disappeared, only qty inflated).

### 3. CI repair PR #1 — commits `5fb9365` + `15ec298`

After pushing the 2 BOM fixes, noticed CI had been failing for 5+
consecutive runs blocking the `deploy` job (gated on `[test, docker]`).

Round 1 (`5fb9365`): mig 061 (`create extension if not exists vector`)
needs pgvector binaries. CI service image was bare `postgres:16`.
Swapped to `pgvector/pgvector:pg16` in both `.github/workflows/ci-cd.yml`
AND `docker-compose.yml`. Same swap required for demo so its next
`docker compose up -d --build` doesn't fail on mig 061.

Round 2 (`15ec298`): CI re-ran further but exposed 3 latent failures.
Investigated:
- `test_accept_unified_no_auto_mapping` + `test_edit_updates_material`
  failed with `CheckViolation: chk_status`. Tracing mig 042 line 122:
  `drop constraint if exists materials_status_check` — but the existing
  constraint (from mig 026) is named `chk_status`. The `IF EXISTS`
  silently no-op'd on fresh DBs, so the old constraint coexisted with
  the new `materials_status_check` constraint. Old constraint rejected
  `status='under_review'`. Local DBs had `chk_status` dropped manually
  long ago, masking the bug.
- `test_technical_raw_upload_confirm_materializes_edges` failed because
  its SELECT didn't filter `source_bom_kind` and post_ingest_hooks
  introduces multiple artifacts per RT_TP product.

Fix: forward-only mig 064 `drop constraint if exists chk_status` (past
migrations immutable per `feedback_bom_vocab.md`); test gets explicit
`source_bom_kind='technical_raw'` filter.

CI green on PR. Took pre-merge backup on demo
(`pre_merge_20260512_212247.dump`), merged, demo auto-deploy fired.
Demo healthz 200, API smoke OK, migrations 042..064 applied cleanly.
LLM `/models` smoke failed with 401 (external endpoint auth) — labeled
"best effort" but step lacks `|| true` so it propagated exit code 22.
Workflow shows as "failure" cosmetically; actual deploy succeeded.

### 4. Johnson rebuild on demo

User asked for the full local-pattern re-ingest mirrored on demo.

Pre-state: demo had 82 technical_raw + 1 manual_flat = 83 BOM
artifacts for Johnson, **0 materials**, 52,224 bcct_rows. The pre-merge
demo never had Johnson catalog/derives wired through; just orphan
uploads.

Sequence:
1. `scp` 106 XLSX (3.9M) to `/tmp/johnson_bom_source/` on demo host.
2. `docker cp` into `data-hub-app-1:/app/data/source_inventory/...`.
3. Pre-wipe backup `pre_wipe_johnson_20260512_230856.dump` (35M).
4. Hard-delete Johnson `bom_artifacts` + children (edges/rows/audit).
5. `scripts/bootstrap_catalog_from_bcct.py --client johnson-vn --commit`
   → 8,702 materials (609 tp + 8,093 nvl).
6. `scripts/ingest_technical_raw_batch.py` → 106 TPs.
7. First pass of post_ingest_hooks: ok=106/0err, but only 212 flat
   artifacts (TPs only). 0 derived BTPs because catalog had no btp_sx
   yet.
8. `scripts/fixup_johnson_btp_sx_after_bom.py --commit` → +2,661 btp_sx
   bom_observed + 1,380 nvl leaf orphans + 370 reclassified
   nvl→btp_sx. Catalog now 12,743 materials.
9. Re-ran post_ingest_hooks. Now derive_btp_shallows minted 3,031 BTP
   raws — but as `status='draft'` because client policy was
   `auto_derive_shallow_from_raw='draft_only'`. Materialize_shapes_hook
   filters `status='published'` → skipped them.
10. Flipped client policy to `publish` + bulk UPDATE
    3,031 derived raws to `published` + ran materialize_shapes_hook
    once. Catch-up materialized 3,031 BTPs → 6,062 new flat artifacts.

Final demo state matches local exactly: 9,411 total (106 TP raw + 3,031
BTP raw + 6,274 flat). BTP `1000534541`: 3 artifacts (1 raw with
canonical 2 edges + 2 flat).

Cleanup: removed `/tmp/johnson_bom_source/` on demo host. Container
`/app/data/source_inventory/...` left in place (will be wiped on next
image rebuild).

### 5. NVL-orphan agency Q&A (deliverable discarded)

User asked for list of NVL codes that appear in BOM but not in BCCT
imports → 1,207 codes (verified across 12 cross-checks). Built an
ad-hoc Excel + Vietnamese message draft for Trọng Tín, then user
asked to delete both files. Export script also removed. No commit.

## Decisions Made

- **Two distinct BOM bugs, two commits, two memory entries.** Initially
  thought parser fix would fully solve fragmentation; empirical
  validation showed a second independent bug (subtree dedup). Both
  fixed in the same session but as separate commits/tests/memories.

- **Branch-and-PR for CI fix** instead of direct push to main, because
  the user had explicitly deferred deploy earlier in the session.
  PR-gated runs only `test` + `docker` jobs; `deploy` gated on push to
  main fires only after merge.

- **Mig 064 forward-only** to drop stale `chk_status`, not modifying
  mig 042 in place. Past migrations are immutable per
  `feedback_bom_vocab.md`.

- **Demo policy flip to `publish`** matches local. The alternative
  (keep `draft_only` + change `list_raw_artifacts_missing_shapes` to
  include draft) would require code change and would hide derived
  state from settlement consumers. Policy flip is the right primitive.

- **Discard ad-hoc export script** per user's "xóa luôn". Reusable but
  one-off enough that re-generation cost is low.

- **Pre-merge backup taken manually** (not via cron) because daily cron
  ran at 02:30 and merge happened ~21:00 — 18 hours of state could be
  lost if rollback needed. RPO 24h policy is acceptable for steady
  state but not for migration-deploy events.

## What Didn't Work

- **First Johnson re-derive on demo (zero derived BTPs)**: ran
  post_ingest_hooks before catalog had btp_sx classifications →
  `_eligible_btp_parents` found nothing → no slices minted. Had to
  re-run hooks AFTER fixup. Future re-ingest order: bootstrap →
  ingest → fixup → hooks → materialize.

- **First nullify-then-delete on local wipe**: attempted to NULL
  `parent_artifact_id` first to satisfy self-FK before deleting
  `bom_artifacts`, hit `UniqueViolation: uq_bom_idempotent_v2`
  because nullifying multiple rows produced duplicate idempotent
  keys. Switched to single DELETE relying on PG to defer self-FK
  check until statement end (works because all referenced parents
  are in the delete set).

- **Materialize hook with `artifact_id=BTP_raw_id` looked like ok=N
  but produced 0 flats**: the hook ignores `artifact_id` parameter
  and iterates `list_raw_artifacts_missing_shapes(client_id)`
  internally. Looked successful but the SQL filter required
  `status='published'` and demo's draft raws didn't qualify. Lesson:
  read the hook implementation, don't trust returned counters
  alone — verify state in DB.

## Open Items

- **Growatt wipe + re-ingest** still pending
  (`project_reingest_pending.md`). Now unblocked, pattern proven.
  On demo this is more involved (Growatt has 467 catalog materials
  from earlier sessions; BCCT depth unknown).

- **CI workflow `Smoke LLM /models` step** marks deploy runs as
  failure even when actual deploy succeeded. Suffix `|| true` would
  fix the cosmetic noise. Or remove the step if LLM smoke is
  no longer informative.

- **NVL-orphan agency Q&A** intentionally not sent. If/when needed
  again, regenerate via direct SQL — full method documented in
  STATUS notes.

- **Demo collation warning** `data_hub was created using collation
  version 2.41, but the operating system provides version 2.36`
  appears on every psql connection. Run
  `ALTER DATABASE data_hub REFRESH COLLATION VERSION` when there's a
  maintenance window.

- **CO consumer migration** for `uom` rename still pending; sister
  app blocker before sunsetting the API alias.
