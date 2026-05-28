# 2026-05-29 — Growatt BOM wipe + re-ingest (F.1)

Closed BACKLOG F.1 (`project_reingest_pending`). BOM-only wipe + fresh
re-ingest on local + demo, end-to-end byte-identical.

## Pre-state

Local DB Growatt BOM: 608 artifacts across 7 mixed variants
accumulated from chained backfills:
- `agency_2026-04-23-btp` 427 (older derive_btp_shallows output)
- `agency_2026-01-supplemental` 93
- `agency_2026-01-root` 42
- `agency_2026-04-23-tp-additional` 18
- `agency_rescued_only_gom` 14
- `agency_2026-04-23` 12
- `default` 2

Source-bom-kind split: 394 technical_flattened (migration/derived) +
198 technical_raw + 15 manual_flat (agency_upload) + 1 stray.

Demo had identical 608/3-kind structure.

## Decisions

- **Scope:** BOM-only wipe. BCCT (38k NK + 916 XK from
  2026-05-28 catch-up), materials catalog, client_config,
  file_uploads all kept. Memory framing of "full client wipe" rejected
  — F.1 is hygiene, not onboarding-redo.
- **Apply to demo same session.** GitOps deploys code, not data,
  so DB sync ran via ssh + docker exec, no CI.
- **Source corpus: 57 XLSX in 3 batches:**
  - `from-bom-15-01/root/` 14 files → `agency_2026-01-root`
  - `from-bom-15-01/supplemental/` 39 → `agency_2026-01-supplemental`
  - `from-bom-20260423/technical/` 4 → `agency_2026-04-23`
  All TP-rooted SAP-indented files; derive_btp_shallows mints BTP
  raw_graphs from the parent_code chain.

## Pipeline (mirror Johnson 2026-05-11 pattern)

1. `pg_dump -Fc` snapshot (local + demo separately)
2. Wipe in single tx: bom_edges → bom_artifact_rows →
   bom_unresolved_nodes → bom_audit_events → bom_change_requests →
   bom_flatten_decisions → bom_presets → bom_artifacts (children
   first, parent last)
3. Set `bom_proposal_mode='manual'` on growatt-vn (bypass auto-rule
   rejection)
4. 3× `scripts/ingest_technical_raw_batch.py` with distinct
   `--variant-id` + `--source-batch` (57 raw_graphs total)
5. `python -m scripts.derive_btp_shallows growatt-vn --status publish`
   → +212 BTP raw_graphs (was 427 pre-2026-05-11 dedup-fix, now 212
   after `_subtree_edges` field-clearing + `parent_artifact_id=None`
   from commit `7552c64`)
6. `scripts/materialize_shallow_and_full_flat.py --client growatt-vn
   --commit --force-publish` → 269 shallow + 269 full_flat
7. Flip `bom_proposal_mode='auto'` back
8. `uv run pytest -q` baseline check

## Final state

Local + demo both:
- 269 raw_graph (57 TP + 212 derived BTP) × 3 shapes = 807 published
- 536 / 271 stale / fresh split — pre-existing UoM gap on 4 catalog
  materials cascading via D7. Not regression.
- 1260 passed, 15 skipped — baseline unchanged

## Snapshots (rollback)

- Local: `/tmp/data_hub_pre_growatt_bom_wipe_2026-05-29_0106.dump`
  (332M, custom format)
- Demo: `~/backups/demo_pre_growatt_wipe_2026-05-29_0116.dump` (305M)

## What was lost — and recovered

16 manual_flat artifacts (15 `agency_rescued_only_gom` BTPs + 1
TEST_TP_DRIFT pair) initially dropped by the wipe — no XLSX source
to replay. User flagged the regression immediately ("Sao lai drop?
Ingest lai thi lai mat du lieu a?"). Restored same session:

1. `pg_restore --data-only -t bom_artifacts -f ...` from snapshot
2. Filter by `client_id='growatt-vn' AND source_bom_kind='manual_flat'`
   → 16 artifact_ids
3. Filter `bom_artifact_rows` (1432 rows) + `bom_audit_events` (16
   rows) by those IDs. `bom_edges` is empty for manual_flat (flat
   artifact stores at row level, no parent/child edges).
4. `psql -f` each filtered file on local + demo. No FK violations.

Filter gotcha: `pg_restore -t bom_audit_events` matches `co.` and
`hub.` schemas (both have that table name); had to strip the
`co.bom_audit_events` COPY block out of the audit dump first.

Final state both DBs: 823 artifacts = 807 re-ingested + 16 restored.
Pytest 1260 still passes.

**Lesson** (now in memory `feedback_wipe_enumerate_unreplayable.md`):
when planning a wipe, enumerate every artifact bucket by source and
flag the ones with no XLSX/script replay path BEFORE deleting. I saw
the 15 manual_flat in the pre-wipe variant breakdown but proceeded —
should have surfaced them as a separate decision.

## Bugs/surprises

None. The Johnson 2026-05-11 dedup fix (`7552c64`) was already in
place, so BTP count came out clean (212 vs old 427).

## What was tried, what changed

- Initial attempt to run wipe SQL via `ssh ... <<'SQL'` heredoc
  silently no-op'd in zsh — wrote `/tmp/wipe_growatt_bom.sql` and
  used `psql -f` instead. Works clean.
- `derive_btp_shallows.py` CLI flags: `--commit` doesn't exist;
  it's `--status publish` (different idiom from materialize).

## Memory updates

- `project_reingest_pending.md` → marked Growatt BOM SHIPPED, full
  pipeline recorded.
- `MEMORY.md` index updated.
