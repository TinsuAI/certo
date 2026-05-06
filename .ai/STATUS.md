# Project Status

**Date:** 2026-05-06 — BOM version UI polish (parent label + Lineage panel)

## Current State

Local code: BOM version pages now show **human-readable parent labels**
(`v#·shape·variant`, click-through) and a **Lineage panel** in the
detail view (ancestors → THIS → descendants, cycle-safe walker). All
rendering moved off inline styles into `static/css/app.css` +
`clients/_bom_macros.html` shared macros.

- **Demo URL**: https://ttdatahub.tinsu.ai
- **Login**: `admin@data-hub.local` / `sS3EZgj9lf5b741`
- **Repo HEAD**: `2d9dbfb` on `main` — **NOT yet pushed** to origin
  (CI/CD will not have run; demo schema/code still at last push
  `8e77996`).
- **Recent commits**:
  - `2d9dbfb` feat(bom): human parent labels + lineage panel
  - `8e77996` docs(backlog): UI BOM upload deferred to Phase 3
  - `6784762` fix(bom): tp_roots + first_seen + demote guard
  - `11409c3` fix(bom): BTP detection covers Johnson-shape
  - `d2899f1` feat(bom): v3 3-shape model + supplier-batch ingest
- **Tests**: 57 BOM tests pass (4.2s); full suite not re-run this
  session — last full run from prior session was 471 pass / 1 fail
  (real-data, deselected) / 15 skip.
- **Local DB v3 state** (unchanged from 2026-05-05):
  - Growatt: 451 materials, 23,080 BCCT, 606 alive `bom_versions` in
    6 variants.
  - Johnson: 11,129 materials, 52,224 BCCT, 246 alive `bom_versions`.
  - DKE: 242 BQD only. Do Thanh, demo-precision: empty.
- **Demo data still OLD** — schema+code on demo at `8e77996`; no data
  re-ingest performed remotely. This was deferred from 2026-05-05
  session and remains the #1 next priority.

## Recent Changes (this session)

See `.ai/sessions/2026-05-06-bom-version-lineage-ui.md` for full
narrative. One commit (`2d9dbfb`) + uncommitted doc/memory/backlog
updates.

**Committed (`2d9dbfb`):**

- `app/stores/bom.py` — `list_versions_for_product` self-joins parent;
  new `get_lineage_for_version()` walker (cycle-safe via `seen` set
  seeded with self, `max_depth=12` with `truncated` flag, surfaces
  `missing_parent_id` when chain breaks at a deleted ancestor).
- `app/routes/bom.py` — derives `version["bom_shape"]` once in route
  via `bom_shape()` helper; passes lineage to detail template.
- `app/templates/clients/bom_versions.html` — parent column renders
  `[v#] [shape_badge] · variant` link; `(deleted)` marker if parent
  row gone.
- `app/templates/clients/bom_version_detail.html` — Lineage panel
  with ancestors → THIS (highlighted) → descendants; "forked from"
  header uses human label.
- `app/templates/clients/_bom_macros.html` (new) — `shape_badge` +
  `lineage_node` macros shared across both templates.
- `app/static/css/app.css` — `.badge-shape-*`, `.lineage-panel`,
  `.lineage-node`, `.lineage-node--current`, etc.
- `.ai/features/2026-05-06-bom-v3-ui-smoke/` — playwright smoke
  harness (`ui_smoke.py`) + 8 committed screenshots verifying
  Growatt SD00.0010600 + Johnson MFW0502-571.
- One round of `/rev` + 7 follow-up fixes (3 Important + 4 Minor)
  done in same commit. See session log.

**Uncommitted (docs + memory + backlog only):**

- `.ai/BACKLOG.md` — added "Modular BOM ingest adapters (per supplier
  shape)" entry. Captures Growatt vs Johnson divergence as an
  ingestion gap, not architectural. Includes `derive_btp_shallows.py`
  spec + adapter registry plan. Bundle with Phase 3.
- Memory `project_bom_3_shapes.md` (NEW) — canonical raw_graph /
  shallow / full_flat definitions + worked example. AI repeatedly
  mis-stated the shallow rule (claimed it never reaches NVL); rule
  is depth-agnostic, stops at first leaf which can be NVL OR BTP.
- Memory `feedback_bundle_rev_fixes.md` (REFINED) — corrected to
  "present all findings including weak ones (labeled), don't self-
  defer; user certifies, default is bundle-execute". User pushed
  back on the original "punch list" framing.
- `.ai/sessions/2026-05-06-bom-version-lineage-ui.md` — extended
  with Post-Commit Discussion section.

## Next Steps

In priority order (item 1 carried forward from 2026-05-05; rest
unchanged unless noted):

1. **Push `2d9dbfb` to origin** — quick win, lets CI/CD deploy the
   UI polish to demo even before data parity. ~5 min.
2. **Demo data parity** — demo has v3 schema but old data. Choose:
   - (a) `pg_dump` local data_hub → scp to tinsu → restore. ~30 min.
     Loses audit chain on tinsu (history triggers re-fire on insert).
   - (b) scp source XLSX corpus to tinsu (~vài GB) → run scripts
     there. ~2-4h. Reproduces audit chain locally on tinsu.
   - Recommendation: (a) for pre-MVP demo; (b) when real customer
     onboards.
3. **Phase 3 — resolver + profiles + sourcing_choice intent**.
   Estimate 25-35h per critic. Bundle UI BOM upload v3 wiring
   (`.ai/BACKLOG.md` "UI BOM upload — wire up v3 concepts") AND
   modular ingest adapters (`.ai/BACKLOG.md` "Modular BOM ingest
   adapters"). Also chốt vào Phase 3: where `derive_btp_shallows.py`
   lives — adapter post-ingest hook vs resolver on-demand.
4. **`detect_dual_source_btps.py`** — small script to flag BTPs
   appearing in BCCT imports as `btp_sourcing='dual_source'`.
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
