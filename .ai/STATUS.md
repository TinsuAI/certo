# Project Status

**Date:** 2026-05-07 — Vocab rename + Phase 3 (resolver / presets / classifier / derive)

## Current State

Phase 3 of BOM resolver work is complete and pushed. Codebase + DB
fully on canonical 4-tier ontology (phiên bản logical / bản lưu /
preset / shape × strategy). Resolver, preset CRUD + UI, btp_sourcing
classifier, and derived BTP shallow artifacts are all live.

- **Demo URL**: https://ttdatahub.tinsu.ai
- **Login**: `admin@data-hub.local` / `sS3EZgj9lf5b741`
- **Repo HEAD**: `0de7292` on `main` — pushed to origin. CI/CD
  picks up the diff.
- **Tests**: 535 pass / 15 skip / 1 pre-existing fail
  (`test_co_columns` real-data, untouched).
- **Local DB v3 state**:
  - Growatt: 451 materials, 23,080 BCCT, 153 BTPs classified
    (148 self_produced_only + 5 dual_source).
  - Johnson: 11,129 materials, 52,224 BCCT, 246 alive
    `bom_artifacts`. Classifier not yet applied.
  - DKE: 242 BQD only. Do Thanh, demo-precision: empty.

### Phase 3 deliverables shipped (this session)

| Sub-phase | Code | Tests | Notes |
|---|---|---|---|
| Rename pass | mig 031 + 44 .py/.html files | 8 | `bv_*` survives, new `ba_*`; 308 URL aliases for one release |
| 3a: Classifier | `scripts/detect_dual_source_btps.py` + catalog UI override + materializer SQL | 14 | Growatt classified live |
| 3b: Resolver | `resolve_bom_artifact()` + preset CRUD endpoints + `/bom` wiring + UI | 27 | preset_id > case_id > shape > default precedence |
| 3c core: Derive | `scripts/derive_btp_shallows.py` + adapter `post_ingest_hooks` contract + multi-role badge | 14 | Closes Johnson 0/342 decomposability gap |
| /rev fix bundle | auth gates + UniqueViolation handler + shape tie-break | +1 | 6 endpoints + 2 race fixes + brief alignment |

### Recent commits (in chronological order)

```
0de7292 fix(bom): /rev Phase 3 — auth gates + UniqueViolation + shape tie-break
dadbd0f feat(bom): Phase 3c core — derive_btp_shallows + adapter hooks + multi-role badge
f5af5d2 feat(bom): Phase 3b — resolver core + preset CRUD + endpoint wiring + UI
5fb814a feat(bom): Phase 3a — btp_sourcing classifier + catalog UI + materializer
a2840cb docs: handoff for BOM vocab rename + Phase 3 brief vocab update
edfa224 refactor(bom): rename version → artifact, profile → preset (mig 031)
27a7889 docs(glossary): canonical BOM vocabulary
```

## Next Steps

Priority order:

1. **Wipe + ingest fresh — Growatt and Johnson** *(pending — user
   chốt 2026-05-07 across three rounds of clarification)*. **Not a
   re-ingest, not a backfill — a one-time pre-MVP reset.** Delete
   every per-client data row (BOM artifacts/edges/audit/proposals/
   unresolved/decisions/presets, BCCT, materials, file_uploads),
   then ingest from source XLSX as if onboarding fresh. Sister apps'
   stored `bv_*` refs (if any) break — acceptable pre-MVP. Full
   procedure in memory `project_reingest_pending.md`. User signals
   when ready.
2. **Demo data parity** — once wipe + ingest fresh runs locally and
   user confirms, mirror to tinsu (`/home/tinsu/data-hub`) via
   `pg_dump → scp → restore` OR re-run scripts on tinsu directly.
3. **Phase 3c follow-ups** (deferred, BACKLOG entry "Phase 3c
   follow-ups") — auto-trigger from upload confirm flow,
   `bom_variant_id` form field, auto-materialize, auto-bootstrap
   BTP roster, shape badge in preview, multi-role warning at upload,
   Playwright E2E. ~10h total, lower-value polish.
4. **Phase 3 review-deferred minors** (BACKLOG entry "Phase 3
   review follow-ups") — catalog↔classifier matching column
   inconsistency, preset name validation thinness, PATCH
   `updated_at` audit column, `derive_btp_shallows` `created` flag
   detection. Batch when convenient.
5. **Restore `bom_proposal_mode='auto'`** for Growatt + Johnson
   after wipe + ingest fresh (currently `manual` from earlier
   re-ingest window).
6. **Sister-repo standards adoption** (carry-over) — CO + BCQT
   need `docs/release-engineering.md`,
   `.standards-version v2026.05.05`, `AGENTS.md` "Standards"
   section.

## Blockers

None hard. Soft (carry-over):
- 14 orphan BTPs Growatt (data quality — staff classify when TP
  context arrives).
- T1-T2/2026 BCCT for Growatt missing (agency hasn't supplied file).

## Notes for Next AI Session

**Read first** (in order): this STATUS, then
`.ai/sessions/2026-05-07-rename-and-phase-3.md` (this session) +
`.ai/sessions/2026-05-06-bom-version-lineage-ui.md` (predecessor) +
the brief at `.ai/features/2026-05-06-phase-3-resolver-profiles/brief.md`
+ rename brief at `.ai/features/2026-05-07-bom-vocab-rename/brief.md`.

**Key memory** (load before reasoning about BOM):
- `project_bom_3_shapes.md` — raw_graph / shallow / full_flat
  canonical definitions; shallow stops at first leaf (NVL OR BTP),
  depth-agnostic.
- `feedback_bom_vocab.md` *(new 2026-05-07)* — post-mig-031 use
  artifact / preset, never version / profile in BOM context.
- `project_reingest_pending.md` *(new 2026-05-07, three rounds of
  clarification)* — wipe + ingest fresh is the pending path. Don't
  preserve `bv_*` history. Don't trigger piecemeal.
- `project_bom_immutable_principle.md` — governs steady-state ops
  (the wipe is one-shot pre-MVP, not a precedent).
- `project_bom_code_multirole.md` — codes can be TP+BTP+NVL
  simultaneously (rework / cải chế).
- `feedback_bundle_rev_fixes.md` — present all /rev findings,
  including weak labeled ones; user certifies; default is
  bundle-execute.
- `feedback_drive_ops_dont_handoff.md` — drive end-to-end via
  ssh.exe / scp.exe / gh; don't hand the user a checklist.

**Architecture / contracts that are LOCKED, don't relitigate**:
- 3-app split (Data Hub + BCQT + CO) — see CLAUDE.md.
- Phase 3 brief decisions D1-D7 (resolver lives in stores/bom.py
  extending, returns provenance trail, derive_btp_shallows runs at
  ingest not query).
- Rename brief decisions D1-D10 (atomic mig, 2 commits, forward-only
  ID prefix `ba_*` / `bp_*`, no feature flag, 308 redirect, etc.).

**Environment quirks**:
- Native Postgres on `/var/run/postgresql` socket, owner `vp`,
  peer auth (`psql -h /var/run/postgresql -U vp -d data_hub`).
- WSL2: Windows OpenSSH (`/mnt/c/Windows/System32/OpenSSH/{ssh,scp}.exe`).
- `vp` user lacks CREATEDB (need `sudo -u postgres createdb`).
- Port 8754 pinned for dev (CO JWT issuer expects exact host).

**Running processes** (as of handoff):
- **uvicorn dev server** background task `bjzy2h75j`, log at
  `/tmp/data-hub-dev.log`. Auto-reload, native Postgres,
  `DATA_HUB_AUTO_SEED_DEMO=0`.

**Sister-app commits unpushed** (on local clones, not Data Hub):
- CO `barry-CO-main` `main`: `ddb9c46` (rename note) +
  newer note `2026-05-07-bom-presets-3b.md` posted but not yet
  committed in CO.
- BCQT `BCQT-System` `dev`: `7732f2b` (rename note).

**Critical user feedback this session**:
- "Wipe, not re-ingest" — three rounds. The data is throwaway
  pre-MVP. Don't worry about BOM-immutable for the planned reset.
- "Bundle-execute" — `/rev` findings get fixed in one commit by
  default; don't self-defer; user certifies.
- "Drive end-to-end" — execute remote ops via ssh.exe / scp.exe;
  don't hand the user a checklist.
