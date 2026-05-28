# Project Status

**Date:** 2026-05-29 PM — F.1 Growatt BOM wipe + re-ingest shipped
on local + demo. 608 mixed-variant artifacts → 823 clean (807
re-ingested + 16 manual_flat restored from snapshot mid-session
after near-miss data loss). A.1 dead-column drop earlier same day
(mig 072) — see prior session.

## Current State

**Branch:** `main` at `03e9c4b`. **Local ahead of `origin/main`
by 1 commit (not pushed). Demo DB synced via direct SQL, NOT via
GitOps** — the F.1 commit is docs-only; no app code changed.

Recent commits (newest first):

- `03e9c4b` — docs(status): F.1 Growatt BOM wipe + re-ingest + restore
- `51503bf` — docs(status): refresh after A.1 closure + mig 072
- `79ae85a` — feat!(catalog): drop unused materials.category_override + override_reason
- `b7f5081` — feat!(bom-api): drop BOM vocab v1 URL aliases (308 → 404)
- `ec528ed` — docs(handoff): CO API trio + quality fixes session

**Tests:** **1,260 passed, 15 skipped** (re-verified post-F.1
restore, baseline unchanged).

**Migrations:** at mig **072**.

**Dev server:** `:8754` running; healthz HTTP 200.

**Demo box (`100.84.189.87:8754`):** at `79ae85a` (HEAD - 1 from
local). Healthz 200. Demo DB Growatt BOM byte-identical with
local (823 / 823).

**Growatt BOM final state both DBs:**

| Bucket | Count |
|---|---|
| TP raw_graph (re-ingest XLSX) | 57 |
| BTP raw_graph derived | 212 |
| Shallow derived (`purchased_btp_as_leaf`) | 269 |
| Full_flat derived (`technical_exploded`) | 269 |
| manual_flat rescued (B710.* + ST01.* etc.) | 14 |
| manual_flat TEST_TP_DRIFT pair | 2 |
| **Total** | **823** |

Johnson untouched: 12,994 artifacts / 65,846 BCCT / 13,132 materials
on both DBs.

## Recent Changes (this session)

**F.1 BACKLOG closure** (Growatt BOM wipe + re-ingest). Pipeline:

1. `pg_dump -Fc` snapshot (local + demo separately)
2. Single-tx wipe of 8 BOM tables scoped `client_id='growatt-vn'`
3. 3× `scripts/ingest_technical_raw_batch.py` (root 14 + supplemental
   39 + 2026-04-23-technical 4 = 57 TP raws)
4. `python -m scripts.derive_btp_shallows growatt-vn --status publish`
   (+212 BTP raws)
5. `scripts/materialize_shallow_and_full_flat.py --force-publish`
   (+269 shallow + 269 full_flat)
6. Flip `bom_proposal_mode='auto'`
7. Pytest baseline

**Near-miss recovery:** wipe dropped 16 `manual_flat agency_upload`
artifacts (14 `agency_rescued_only_gom` BTPs from 2026-05-05
`cleanup_gom_phase.py` rescue session + 2 TEST_TP_DRIFT). These had
no XLSX source to replay. User flagged ("Sao lai drop?"). Restored
via filtered `pg_restore --data-only` from snapshot, on local + demo.
Lesson saved to memory `feedback_wipe_enumerate_unreplayable.md`.

**Files committed:** `.ai/STATUS.md`, `.ai/sessions/2026-05-29-growatt-bom-wipe-reingest.md`.

**Memories updated:**
- `project_reingest_pending.md` — Growatt BOM marked SHIPPED with
  full pipeline + restore note
- `feedback_wipe_enumerate_unreplayable.md` — new feedback memory
  for the lesson
- `MEMORY.md` — index entries updated

## Next Steps

1. **Optional `git push`** — `03e9c4b` is local-only. Demo already
   has the data state via direct sync, so push is not blocking. Only
   needed if the F.1 session log should be on GitHub.
2. **Repo hygiene** — untracked sessions from earlier weeks
   (`2026-05-15-catalog-conflicts-page-ship.md`,
   `2026-05-15-m16-ingest-and-uom-evidence-audit.md`,
   `2026-05-25-bulk-zip-upload-shipped.md`,
   `2026-05-28-bom-vocab-v1-alias-drop.md`,
   `2026-05-29-a1-dead-column-drop.md`); untracked scripts
   (`generate_training_input_scenarios.py`, `uom_drift_report.py`);
   untracked `docs/training/` dir; 31 modified files under
   `.ai/features/2026-05-04-demo-company-feed/` (screenshots +
   manifests). Triage in a future session.
3. **A.4.3 follow-up if needed** — normalize-then-bucket gives 21%
   noise reduction on Johnson per-product codes. Only worth more
   work if staff complain.
4. **D.1 Aggregate-data git-history** — large principle work
   (materials/code_mappings/client_config history tables + revert
   UI). Needs `/discover` first.
5. **STATUS open items unchanged** — offsite backup missing (single
   VPS = SPOF); ALARM file → external alert (user passed on this
   one explicitly).

## Notes for Next AI Session

- **F.1 snapshots are on disk** in case rollback ever needed: local
  `/tmp/data_hub_pre_growatt_bom_wipe_2026-05-29_0106.dump` (332M),
  demo `~/backups/demo_pre_growatt_wipe_2026-05-29_0116.dump` (305M).
  `/tmp/` survives between sessions on this dev box but is not
  guaranteed — move to a persistent location if you want long-term
  rollback safety.
- **Wipe discipline:** before any "wipe + replay" operation,
  enumerate every artifact bucket by `(variant_id, source_channel,
  source_bom_kind)` and identify which have no replay source — see
  memory `feedback_wipe_enumerate_unreplayable.md`. The Growatt
  near-miss happened because I saw 15 `manual_flat` in the variant
  breakdown but didn't flag them as unreplayable before deleting.
- **Demo data sync without code change:** since F.1 was data ops
  only (no app code), I synced demo directly via `ssh + docker exec`
  rather than push-to-main → CI-deploy. Pattern: snapshot →
  identical SQL via psql -f → re-run ingest scripts inside
  `data-hub-app-1` container with `uv run python /app/scripts/...`.
  Source XLSX shipped via `tar` + scp + `docker cp`.
- **`category_override` / `override_reason` dropped on local + demo
  (mig 072).** Any caller reading those JSON fields from
  `/v1/hub/.../catalog/...` gets nothing. None known. CO consumes
  `category` (verified by grep), not the override.
- **Discovery lesson:** A.1 was scoped as "2-3 day cross-cut
  refactor" in BACKLOG. Data audit before committing showed the
  pain was hypothetical. Quick query against the dev DB
  (`select count(*) filter (where category_override is not null)`)
  collapsed the scope from refactor to dead-code drop. Worth doing
  before any "large scope" item — verify the pain is real.
- **Alias drop (commit `b7f5081`) is live.** Old `/bom/version/...`
  paths return 404, not 308. CO + BCQT verified clean pre-ship.
- **Demo log retention is NIL across deploys.** `data-hub-app-1`
  container is `restart: unless-stopped`, started fresh on every CI
  push. `docker logs` only covers since-last-restart. `/var/log/nginx/`
  needs root and is unused anyway (all traffic direct to uvicorn:8754).
  This means "zero alias hits in 24h" type removal triggers can't be
  strictly verified — fall back to caller-side grep + grace-period
  duration when this comes up again.
- **Conftest force-resets admin password** to `admin123` (PM-session
  fix). Real seed is `local_test_password`. Running `pytest` once
  flips it; if you can't log in to UI after running tests, that's why.
- **CO pre-staged consumers** for the 3 PM-session endpoints use
  `filter_applied` / `server_time` probes so no coordinated deploy
  needed.
- **Demo deploy is GitOps via GitHub Actions** — every push to main
  triggers CI build + deploy. ~1.5-2 min per cycle. `gh run watch
  <id> --exit-status` for sync; verify with `ssh tinsu@100.84.189.87
  cd ~/data-hub && git log -1`.
- **Use Windows `ssh.exe`** for demo: `/mnt/c/Windows/System32/OpenSSH/ssh.exe
  tinsu@100.84.189.87 ...`. WSL ssh broken. Docker reachable via
  `docker exec data-hub-db-1`.
- **Dev server hot reload is OFF** (4 workers; `--workers N` not
  compatible with `--reload`). Restart manually after code changes:
  `pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 8754";
  nohup uv run uvicorn ... &`. The PM-session note about this was
  re-confirmed today — easy to forget.
- **STATUS-counts vs reality:** baseline test count drifts every
  session. Re-check with `uv run pytest -q` rather than trusting
  STATUS.md.
