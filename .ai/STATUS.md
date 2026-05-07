# Project Status

**Date:** 2026-05-07 — BOM vocab rename pass (artifact / preset)

## Current State

Local code + DB: BOM canonical 4-tier ontology (phiên bản logical /
bản lưu storage / preset / shape × strategy) is now the single
vocabulary across schema, store, route, template, test, and docs.

- Mig 031 renamed `bom_versions` → `bom_artifacts`,
  `bom_resolution_profiles` → `bom_presets`, plus 9 column renames
  spanning 7 tables. PG ALTER TABLE/COLUMN RENAME is metadata-only.
- 44 .py + .html files updated via grep-replace + targeted edits.
- ID prefix forward-only: existing `bv_*` rows kept; new artifact
  rows mint `ba_*`.
- 308 redirect aliases preserve old URLs for one-release grace
  (`/bom/version/...`, `/bom/.../versions`, API endpoint).
- 8 vocab-rename tests added; full suite **479 pass / 15 skip / 1
  pre-existing fail** (test_co_columns real-data, untouched).

- **Demo URL**: https://ttdatahub.tinsu.ai
- **Login**: `admin@data-hub.local` / `sS3EZgj9lf5b741`
- **Repo HEAD**: rename pass landed locally — to be committed +
  pushed (rev pending). Demo currently at `27a7889` (latest pushed
  before rename).
- **Recent commits**:
  - `27a7889` docs(glossary): canonical BOM vocabulary
  - `bd551b1` docs: handoff for BOM lineage UI session
  - `2d9dbfb` feat(bom): human parent labels + lineage panel
- **Local DB v3 state** (unchanged from 2026-05-05):
  - Growatt: 451 materials, 23,080 BCCT, 606 alive `bom_artifacts` in
    6 variants.
  - Johnson: 11,129 materials, 52,224 BCCT, 246 alive `bom_artifacts`.
  - DKE: 242 BQD only. Do Thanh, demo-precision: empty.
- **Demo data still OLD** — schema+code on demo at `8e77996`; no data
  re-ingest performed remotely. This was deferred from 2026-05-05
  session and remains the #1 next priority.

## Recent Changes (this session)

Vocab rename pass — see brief
`.ai/features/2026-05-07-bom-vocab-rename/brief.md` and feature folder
for full plan. To-be-committed (rev pending):

**Schema (mig 031, applied locally):**
- `bom_versions` → `bom_artifacts`
- `bom_version_rows` → `bom_artifact_rows`
- `bom_resolution_profiles` → `bom_presets`
- `version_id` → `artifact_id` (cross-table: bom_artifacts,
  bom_artifact_rows, bom_audit_events, bom_unresolved_nodes,
  bom_edges, bcct_rows)
- `version_no` → `artifact_no`
- `parent_version_id` → `parent_artifact_id`
- `materialized_version_id` → `materialized_artifact_id`
- `profile_id` → `preset_id`, `bom_version_id` → `artifact_id` in presets
- 9 indexes renamed; 3 PK constraints renamed
- Generated column `parent_norm` auto-updated by Postgres

**Code (44 files):**
- Bulk regex replace across .py + .html (table/column refs).
- Function renames: `list_versions_for_product` → `list_artifacts_for_product`,
  `get_version_with_rows` → `get_artifact_with_rows`,
  `get_lineage_for_version` → `get_lineage_for_artifact`.
- URL paths: `/bom/version/` → `/bom/artifact/`, `/bom/.../versions`
  → `/bom/.../artifacts`.
- Template renames: `bom_versions.html` → `bom_artifacts.html`,
  `bom_version_detail.html` → `bom_artifact_detail.html`.
- ID prefix: `"bv_"` → `"ba_"` (2 sites in `app/stores/bom.py`).

**Aliases (one-release grace, BACKLOG entry tracks removal):**
- `_alias_artifact_detail`, `_alias_artifacts_list` in `app/routes/bom.py`.
- `_alias_api_bom_versions` in `app/routes/api.py`.
- All return `308 Permanent Redirect` with new URL.

**Tests:**
- `tests/test_bom_vocab_rename.py` (new, 8 tests) — 4 schema asserts,
  3 alias 308 asserts, 1 ID-prefix assert.
- Full suite: 479 pass / 15 skip / 1 pre-existing fail.

**Docs:**
- `docs/API_CONTRACT.md` + `docs/API_CHANGELOG.md` updated.
- `.ai/STATUS.md`, `.ai/DECISIONS.md` (new entry), `.ai/BACKLOG.md`
  (new "Drop BOM vocab v1 aliases" entry), `README.md`.

## Next Steps

In priority order:

1. **Phase 3 done — confirm + push** (3 commits pending: `5fb814a`
   3a, `f5af5d2` 3b, plus 3c commit forthcoming). Push to origin
   when user signals ready.
2. **Phase 3c follow-ups** — UI upload v3 wiring + Playwright E2E
   tracked in `.ai/BACKLOG.md` "Phase 3c follow-ups". Deferred as
   lower-value polish; core 3c (`derive_btp_shallows` + adapter
   hooks contract + multi-role warning) shipped.
3. **Wipe + ingest fresh — Growatt and Johnson** *(pending — user
   noted 2026-05-07, three rounds of clarification)* — after all
   Phase 3 fixes ship, **delete every per-client data row**
   (BOM artifacts/edges/audit/proposals/unresolved/decisions/presets,
   BCCT, materials, file_uploads) for both clients, then ingest
   from source XLSX as if onboarding fresh. **Not a re-ingest, not
   a backfill — a one-time pre-MVP reset.** Sister apps' stored
   `bv_*` IDs (if any) break — acceptable pre-MVP. See memory
   `project_reingest_pending.md` for full procedure (snapshot first,
   truncate dependency order, restore proposal_mode auto, ingest
   pipeline order).
4. **Demo data parity** — apply mig 031 on tinsu + sync data
   (deferred from earlier sessions; lower priority once re-ingest
   plan above lands).
5. **Push commits to origin** — `5fb814a` (Phase 3a) on local
   `main`, not yet pushed.
6. **`docs/release-engineering.md`** updates — document mode-aware
   reference data + v3 ingest pipeline as standard ops procedures.
5. **`docs/release-engineering.md`** updates — document mode-aware
   reference data + the v3 ingest pipeline as standard ops procedures.
6. **Sister-repo standards adoption** (carry-over) — CO and BCQT
   need `docs/release-engineering.md`, `.standards-version v2026.05.05`,
   `AGENTS.md` "Standards" section.
7. **Restore `bom_proposal_mode='auto'`** for Growatt+Johnson when
   ready (currently `manual` from re-ingest window).
8. **Cleanup stale upload state** — 24 file_uploads in
   mapping_pending / pending_preview from old smoke runs.

## Blockers

None hard. Soft (carried over):
- 14 orphan BTPs Growatt (data quality — staff classify when TP
  context arrives).
- T1-T2/2026 BCCT for Growatt missing (agency hasn't supplied file).

## Notes for Next AI Session

**Read first**: this STATUS, then
`.ai/sessions/2026-05-06-bom-version-lineage-ui.md` (this session) +
`.ai/sessions/2026-05-05-bom-v3-redesign-and-reingest.md` (predecessor),
then memory files for design principles.

**Key memory**:
- `project_bom_immutable_principle.md`
- `project_bom_code_multirole.md`
- `project_growatt_bom_v1_v2_equivalence.md`
- `reference_dev_db_topology.md`
- `project_bom_3_shapes.md` (NEW 2026-05-06) — canonical raw/shallow/
  full_flat definitions. **Read before reasoning about BOM shape**
  to avoid the "shallow stops at level 1" misconception.
- `feedback_bundle_rev_fixes.md` (REFINED 2026-05-06) — present all
  /rev findings including weak ones; user certifies; default
  proposal is bundle-execute.

**Environment quirks**:
- Native Postgres on `127.0.0.1:5432` via unix socket, owner `vp`,
  peer auth (`psql -h /var/run/postgresql -U vp -d data_hub`).
- WSL2: Windows OpenSSH (`/mnt/c/Windows/System32/OpenSSH/{ssh,scp}.exe`).
- `vp` user lacks CREATEDB privilege (need `sudo -u postgres createdb`).
- Port 8754 pinned for dev (CO JWT issuer expects exact host).

**Running processes** (as of handoff):
- **uvicorn dev server** still running, background task `bxx7b797v`,
  log at `/tmp/data-hub-dev.log`. Auto-reload on file changes. Native
  postgres backend, `DATA_HUB_AUTO_SEED_DEMO=0`.
- Docker compose `data-hub-app-1` + `data-hub-db-1` were stopped at
  start of this session; bring back only if compose-shape testing is
  needed.

**UI smoke harness pattern** (introduced this session):
- `.ai/features/<YYYY-MM-DD-slug>/ui_smoke.py` — playwright headless
  script targeting real client/product (not auto-seed INV-3000).
- Captures both `full_page=True` (regression evidence) and viewport-
  only (`full=False`, focus on top of page where new UI lives).
- Screenshots committed under `screenshots/`; small (<1MB each), worth
  the repo size for future regression diffing.
- Reusable for future UI changes; copy + adjust `TARGETS` list.

**`/rev` discipline**: after non-trivial UI work, ran `/rev` and
fixed all 7 findings in same commit before /handoff. User explicitly
preferred bundled fix (`Tại sao không fix hết luôn đi?`). Treat that
as the default for code-review output: fix all in same commit unless
findings are large enough to warrant separate PRs.

**Critic-driven decisions worth re-reading before changing them**
(unchanged from 2026-05-05):
- Don't drop `flatten_status` + `flatten_strategy` (170 refs).
- `bom_variant_id` per supplier batch (not 'default' for all).
- `bom_proposal_mode='manual'` during re-ingest, flip back later.
- `auto_derive_shallow_from_raw='draft_only'` default.
- Profile cardinality is small (strategy-level, not shipment-level).
- Inventory ledger deferred — Phase 6+, not in MVP.
