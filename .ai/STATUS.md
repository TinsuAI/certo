# Project Status

**Date:** 2026-05-13 — Shipped 2 BOM data-quality fixes (commits
`9d1984f`, `7552c64`), 1 CI/deploy repair PR (#1, merged as `44813c2`),
and re-built Johnson end-to-end on demo. All work pushed to `origin/main`.

## Current State

**Branch:** `main` at `15ec298` (= origin/main). 4 commits added this
session: `9d1984f` parser fix, `7552c64` subtree dedup, `5fb9365` CI
pgvector image, `15ec298` chk_status drop + flake fix.

**Tests:** 1082 passed, 15 skipped. The previously pre-existing flake
`test_technical_raw_upload_confirm_materializes_edges` is now FIXED
(filter on `source_bom_kind='technical_raw'` added).

**Working tree:** Untracked-only — `docs/training/` +
`scripts/generate_training_input_scenarios.py` from prior session.
No staged/unstaged code changes.

**Migrations:** at mig 064 (this session added `064_drop_legacy_chk_status_constraint.sql`).

**Dev server:** `:8754` workers=4, log `/tmp/dh_dev.log`.

**Local Johnson BOM** (post wipe + reingest):
- 106 TP raws + 3,031 derived BTP raws + 6,274 flat = 9,411 total.
- BTP `1000534541` collapsed 21→3 (one canonical raw, 2 children, 2 flat).
- Backup: `/tmp/dh_backups/data_hub_pre_qty_fix_20260512_003330.dump` (127M).

**Demo** (`http://100.84.189.87:8754`):
- HEAD: `44813c2` (12 migrations applied 042..064, image swapped to
  `pgvector/pgvector:pg16`).
- Johnson BOM matches local exactly (9,411 artifacts, same BTP collapse).
- Catalog: 12,743 materials (609 tp + 3,031 btp_sx + 9,103 nvl) —
  bootstrap from BCCT 8,702 + fixup added 2,661 btp_sx + 1,380 leaf
  nvl + 370 reclassified nvl→btp_sx.
- Client policy: flipped `auto_derive_shallow_from_raw='publish'` so
  derive_btp_shallows + materialize_shapes auto-flow on future ingests.
- Backups: `/home/tinsu/backups/data-hub/pre_merge_20260512_212247.dump`
  (35M, pre-deploy) + `pre_wipe_johnson_20260512_230856.dump` (35M,
  pre-wipe).

## Recent Changes — this session

**4 commits to main + 1 merged PR:**

1. `9d1984f fix(bom): SAP indented parser picks per-parent qty (MENGE)
   over cumulative (MNGKO)` — swap `_QTY_ALIASES` order in
   `app/parsers/bom_adapters/sap_indented_walk.py`. Affects both
   bulk-ingest and WebUI upload paths (same alias list shared).
   12.6% Johnson rows previously contaminated with cumulative qty.

2. `7552c64 fix(bom): _subtree_edges dedups multi-position BTP
   occurrences` — output dedup keyed by tuple in
   `scripts/derive_btp_shallows.py::_subtree_edges`. BTP slice is a
   per-unit-of-BTP definition; multi-position usage scales the
   parent_TP→BTP edge, not the BTP-internal sub-tree.

3. `5fb9365 fix(ci): swap to pgvector/pgvector:pg16 for postgres
   service` — CI failed since `dcc6216` (Johnson onboarding) because
   mig 061 needs pgvector binaries. Applied to both
   `.github/workflows/ci-cd.yml` AND `docker-compose.yml`.

4. `15ec298 fix(ci): unblock 3 remaining CI failures (chk_status drop +
   flaky test scope)` — mig 064 drops stale `chk_status` constraint
   (mig 042 had typo `materials_status_check` that no-op'd on fresh
   DBs); `test_technical_raw_upload_confirm_materializes_edges` filter
   `source_bom_kind='technical_raw'`.

**Memory entries updated (2):**
- `project_sap_parser_qty_bug.md` — marked SHIPPED 2026-05-12, commit `9d1984f`.
- `project_bom_subtree_dedup.md` — NEW, documents 2nd bug + fix.

## Next Steps

Priority order:

1. **Growatt wipe + re-ingest** (`project_reingest_pending.md`). Now
   unblocked — pattern proven on Johnson local + demo. Estimated 0.5d.
   On demo this is more involved (Growatt has 467 catalog materials
   from earlier sessions; BCCT depth unknown).

2. **CO consumer migration** (sister-app, no grace window). CO must
   update `data_hub_client.normalize_material_row` to read `uom`
   (not `unit`). After CO ships, drop the `m.uom AS unit` alias in
   `app/routes/api.py` + `app/routes/catalog.py` + `app/agent/tools.py`.
   Sunset 2026-05-25 in API_CONTRACT (placeholder; can be sooner).

3. **Demo collation warning** (`data_hub` was created with collation
   v2.41 but OS provides v2.36). Cosmetic, but worth running
   `ALTER DATABASE data_hub REFRESH COLLATION VERSION` on demo when
   stable. Currently appears on every psql connection.

4. **CI workflow polish**: `Smoke LLM /models (best effort)` step
   currently exits 22 on auth-failure → marks whole run failed even
   though deploy succeeded. Suffix with `|| true` to make truly
   best-effort.

5. **Vietnamese customs multi-meaning tokens** (Phase 2 follow-up):
   `client_parser_rules` for `Chai/Lọ/Tuýp`, `SOI`, `Thanh/Mảnh/Miếng`,
   `Viên/Hạt`, `Kiện/Hộp/Bao/Gói`. ~0.5d. Inventoried in
   `.ai/features/2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md`.

## Blockers

None. 220-code factor file from Johnson agency (cross-family UoM
conversion) still pending agency response but is not a dev blocker.

## Notes for Next AI Session

- **Two BOM bugs were sequential**: Parser fix (MENGE vs MNGKO) only
  got BTP 1000534541 from 21→9; required additional dedup fix to reach
  3. If similar fragmentation seen elsewhere, check BOTH `bom_edges.qty`
  values AND `_subtree_edges` output for multi-position artifacts.

- **NVL-in-BOM-but-not-in-BCCT-import gap on Johnson**: 1,207 codes
  (verified via 12 cross-checks). All have `source='bom_observed'` and
  `code_kind='unified'`. This list belongs in a Q&A round with the
  Johnson agency (Trọng Tín contact). Ad-hoc Excel export was generated
  and discarded per user request; if needed again, regenerate from
  `bom_children EXCEPT bcct_imports JOIN materials WHERE category='nvl'`.

- **Demo client policy quirk**: Demo Johnson was `auto_derive_shallow_from_raw='draft_only'`
  pre-flip, which caused `materialize_shapes_hook` to skip 3,031 derived
  BTP raws (its filter requires `status='published'`). Flipping to
  `publish` is the right state to match local. If a new client onboard
  uses `draft_only`, expect derived BTPs to stay invisible to flatten
  until policy flips.

- **Materialize order matters**: On demo, post_ingest_hooks ran BEFORE
  the BTP_SX fixup catalog repair → derive_btp_shallows found 0 eligible
  parents (no btp_sx in catalog yet) → 0 derived BTPs. Required re-running
  hooks AFTER fixup. Future re-ingest order should be:
  bootstrap_catalog → ingest BOM → fixup_btp_sx → run hooks → materialize.

- **CI was broken since `dcc6218`** (5+ runs failing). Now fully green.
  Any future migration that uses a new Postgres extension must verify
  the image ships it, or add an explicit install step.

- **Demo Tailscale outage at session-end (2026-05-13 ~17:30 ICT)**:
  After all demo work landed and was verified green (9,411 artifacts,
  BTP 1000534541 collapse, etc.), Tailscale relay `hkg` started timing
  out on ssh/http/ping to `100.84.189.87`. Node still shown as `active`
  by `tailscale status`. User accepted "trust demo state pre-outage"
  since compose has `restart: unless-stopped` and Postgres uses
  persistent volume. **Next session must re-verify** demo healthz +
  Johnson artifact counts when Tailscale recovers — query template
  in the session log §1 final validation block.

- **Demo backups will accumulate**: `/home/tinsu/backups/data-hub/`
  has 30-day retention via cron. The ad-hoc `pre_merge_*` /
  `pre_wipe_*` dumps this session are NOT in that cron's retention
  loop — they'll sit until manually removed. Consider periodic
  cleanup.

- **Demo backups will accumulate**: `/home/tinsu/backups/data-hub/`
  has 30-day retention via cron. The ad-hoc pre_merge/pre_wipe dumps
  this session are NOT in that cron's retention loop — they'll sit
  until manually removed. Consider periodic cleanup.
