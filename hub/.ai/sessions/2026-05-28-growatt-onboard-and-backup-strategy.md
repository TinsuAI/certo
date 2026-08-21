# Session — Growatt 2026-05 onboarding + volume bug fix + backup pipeline

**Dates:** 2026-05-27 evening → 2026-05-28 (continuous, crossed midnight).
**Branch:** `main`.
**Commits:** `b19c88e` pushed to `origin/main` and deployed to demo.

## What Was Done

### 1. Growatt BCCT ingest — local + demo, byte-identical end state

Source archive: `P:\Downloads\drive-download-20260527T150852Z-3-001.zip`
containing:
- `BaoCaoHangChiTiet ALL NK GRW (20.05.2026).xls` (29 MB)
- `BaoCaoHangChiTiet ALL XK GRW (20.05.2026).xls` (725 KB)
- `TKN.zip` → 3,541 per-decl XLS (2.2 GB extracted)
- `TKX.rar` → 500 per-decl XLS/XLSX (RAR5 format)

Staged into `data/source_inventory/growatt-vn/2026-05-27/`.

Pipeline (mirrored on demo):
1. Bulk BaoCao via ad-hoc Python invoking `app.parsers.bcct.parse_bcct_workbook`
   + `app.routes.bcct._insert_bcct`. Upsert on
   `(client_id, year, transaction_key, line_no)` → idempotent re-ingest.
2. Per-decl files via `scripts/import_declaration_archive.py`
   (`--direction import|export`). Dedup on
   `(client_id, decl_no, direction, sha256)`.

**Counts (local = demo after deploy):**

| | Before | After |
|---|---|---|
| NK bcct_rows | 22,414 (759 decls) | **38,287 (1,403 decls)** |
| XK bcct_rows | 666 (344 decls) | **916 (500 decls)** |
| NK declaration_files | 0 | **3,538** |
| XK declaration_files | 0 | **500** |
| Date range | up to 2026-04-21 | up to **2026-05-20** |

**Skipped at ingest:** 15 NK + 6 XK rows with null `Ngày ĐK`; 3 NK
per-decl files failed parse (2× filename↔content decl_no mismatch,
1× no 10-14 digit decl in first 25×32 cells). All upstream data
issues, identical to Johnson onboarding pattern; not blockers.

### 2. Pre-existing volume mount bug found + fixed

Discovered while running the new backup script: `appfiles-2026-05-27.tar.zst`
came out at 4 KB. Investigation:

- `docker-compose.yml:32` set `DATA_HUB_FILES_DIR=/var/lib/data-hub/files`
- `app/storage/__init__.py:68` and `app/data_promotion.py:177`
  read `DATA_HUB_FILES_ROOT` (different env name)
- Result: env var ignored, code fell back to default
  `Path("data/files").resolve()` → `/app/data/files` (container
  writable layer, NOT the mounted volume)
- Named volume `appfiles` was mounted at `/var/lib/data-hub/files`
  but never written to (4 KB empty dir)
- **2.2 GB / 4,038 file blobs (Johnson + Growatt declaration files,
  catalog uploads, BCCT uploads) sat on the ephemeral container
  layer.** Any `docker compose up -d --build` or container recreate
  would have vaporized them. DB metadata would survive but every
  `backend_key` would 404.

Bug existed since LocalFS storage was wired up. Container had been
up 8 hours — would have been lost on the next CI auto-deploy (which
fires on every push to main and runs `docker compose up -d --build`).

**Fix (commit `b19c88e`):**
1. Rename env to `DATA_HUB_FILES_ROOT` in `docker-compose.yml` +
   `deploy/env.template` to match code.
2. Cancel pending CI auto-deploy via `gh run cancel 26523067700` —
   would have wiped the container layer before migration.
3. Migrate data in the running container:
   `docker exec data-hub-app-1 sh -c 'cp -a /app/data/files/. /var/lib/data-hub/files/'`
   (cp -a not mv: keeps source intact so rollback is just revert+up).
4. Pull on demo, `docker compose up -d` (no `--build` — env-only diff
   recreates app container, db service unchanged).
5. Verified: env now reads correct name, volume has 4,038 files /
   2.2 GB, sample backend_key path resolves on disk.

`keys_dir` was clean: code reads `DATA_HUB_KEYS_DIR`, compose sets
`DATA_HUB_KEYS_DIR` — already matched. Only `files` was misaligned.

### 3. Backup pipeline replacing postgres-only daily

Existing infra (kept): `tinsu` user crontab daily 02:30 calling
`deploy/scripts/backup-postgres.sh` → `~/backups/data-hub/YYYY-MM-DD.dump`,
30-day retention, verifies via `pg_restore --list`. 24 daily dumps
already in place going back to 2026-05-04.

Critical gaps identified:
1. `appfiles` volume not backed up (now contains 2.2 GB of legal
   evidence blobs)
2. `appkeys` volume not backed up (JWT signing keys → losing them
   invalidates all sessions + breaks sister-app auth)
3. No offsite copy (user opted: local-only this session)
4. No restore drill ever run

**Shipped (commit `b19c88e`):**

- `deploy/scripts/backup-data-hub.sh` — daily umbrella. Three outputs
  + status file:
  - `db-YYYY-MM-DD.dump` (pg_dump custom, 305 MB)
  - `appfiles-YYYY-MM-DD.tar.zst` (tar via throwaway alpine + zstd,
    167 MB compressed from 2.2 GB raw)
  - `appkeys-YYYY-MM-DD.tar.zst` (300 B — legitimately small)
  - `status-YYYY-MM-DD.txt` PASS|FAIL with sizes
  - `ALARM` file written on FAIL (cleared on next PASS)
  - 30-day retention, auto-prune

- `deploy/scripts/restore-drill.sh` — weekly drill. Boots scratch
  `pgvector/pgvector:pg16` container, `pg_restore` newest dump,
  asserts:
  - `bcct_rows >= 1000`
  - `declaration_files >= 1`
  - dump age <= 2 days
  Writes `drill-YYYY-MM-DD.txt` + appends one line to drill log.
  ALARM on FAIL. Container torn down on EXIT trap.

- `deploy/cron.d/data-hub` — template updated. Demo `tinsu` crontab
  rewritten to point at new umbrella script + adds Sunday 04:30 drill.

**First runs PASS (manual, on demo):**
- Backup: db=305M, appfiles=167M, appkeys=300B, status=PASS
- Drill: bcct=105,049 / files=7,259 / bom=13,602 / mat=13,589 — all
  restore-checked from `db-2026-05-27.dump`

### 4. Tooling note: RAR5 extraction

`TKX.rar` is RAR5 (`Method = m3:19`, `Version = 29`). `7z 23.01` on
Linux silently extracts ONLY the first file from a multi-file RAR5
archive — no error, no warning, just stops at file #1. Lost a few
minutes debugging.

Workaround: `uv pip install rarfile` → wrapper around system `unrar`
binary. Python's `rarfile.RarFile(...).extractall()` extracted all
500 files correctly. Saved as memory.

## Decisions Made

- **Skip offsite tier** (user explicit): local-only daily backup is
  the floor; offsite (R2/GDrive/VPS-2) deferred to a future session
  with explicit destination choice.

- **Tier 4 drill weekly, not daily**: drill spins up a 500MB
  scratch container + does a full restore (~80s). Daily would burn
  cycles for low marginal value; weekly catches dump corruption
  within ~7 days of occurrence.

- **`cp -a` not `mv` for the migrate step**: keeping source intact
  meant rollback was just `git revert + docker compose up -d` —
  no data motion required.

- **Cancel CI before fix**: GitHub Actions `Deploy to tinsu` job
  was 9 seconds in. Letting it run would have rebuilt the image,
  recreated the container, and wiped 2.2 GB of files between the
  push and the manual `cp -a`. Cancelled, did the migrate, then
  did a clean `docker compose up -d` (no build).

- **No `--build` on the demo redeploy**: env-only change, image
  unchanged. `up -d` recreates the container with new env without
  the 5-minute buildx step.

- **ALARM file pattern instead of email**: demo has no MTA + user
  asked to skip offsite, so external alert delivery is out of
  scope. ALARM is a single file in `~/backups/data-hub/` that
  shows up on next admin shell. Cheap, visible, no infra.

## What Didn't Work

- **First TKX extract via `7z x`** — only got 1 file silently.
  `7z l` showed all 501 entries fine. Tried `-bd`, `-bb3`, flat
  `7z e`, all silent partial extracts. Found `7z 23.01`'s RAR5
  decoder is broken on multi-file archives on this Linux build.
  Switched to `python rarfile` (wraps `unrar`) → all 500 files.

- **First `backup-data-hub.sh` run** — `appfiles-*.tar.zst` came
  out 4 KB. Triggered the bug investigation above. Script itself
  was correct; the volume was just empty due to env mismatch.

- **`docker exec ... pg_dump -U data_hub`** — first dump attempt
  used `data_hub` as the role name. Demo's POSTGRES_USER is `hub`
  (per `~/data-hub/.env`). Re-ran with `-U hub`.

- **`scp -r /…/TKX` from local to demo was slow** — Tailscale
  link gave ~1.5 MB/s for 500 small files. 60 MB took ~5 minutes
  of `ssh.exe` round-trips. Lesson: for next bulk transfer, tar
  locally first then send one big stream (the `unrar` workaround
  + transfer was net-faster than `scp -r`).

## Open Items

- **Offsite copy** still not implemented. Single VPS = single point
  of failure. Defer requires user to pick destination
  (Cloudflare R2 / GDrive / second VPS).

- **Email/Telegram alert** for ALARM file. Demo crontab has Zalo
  monitor comments but no actual webhook lines accessible. Next
  session worth wiring a 1-line cron that posts ALARM contents to
  whatever notification channel the user uses for ops.

- **Pre-existing test fail** `tests/test_declarations_bulk_upload_route.py`
  — 5 tests fail on HEAD too with `401 Unauthorized` against
  `admin@data-hub.local`. Looks like a seed-password env fixture
  issue, not session-introduced. Unrelated, needs a separate
  small PR.

- **Collation version warning** on every demo psql connection
  (`collation 2.41 vs OS 2.36`) — flagged in 2026-05-13 session,
  still pending an
  `ALTER DATABASE data_hub REFRESH COLLATION VERSION` during a
  maintenance window.

- **3 NK files with parse errors** for Growatt (filename↔content
  mismatch + missing decl). Identical pattern to Johnson —
  agency-supplied data issue, not parser bug. Could be surfaced
  in a "files-with-issues" UI report if useful.

- **Bulk BaoCao ingest is ad-hoc**: ran inline Python script,
  identical pattern to `scripts/ingest_johnson_real.py`. Worth
  promoting a parameterized `scripts/ingest_baocao.py
  --client <id> --nk <path> --xk <path>` so it's not a copy-paste
  per client/per onboarding. Defer.

## Notes for next session

- Demo at `b19c88e` (HEAD = origin/main). Local sync verified.
- Container app age = 5 min as of session end (recreated for env
  fix). DB container age 2 weeks (unchanged).
- Cron: daily 02:30 `backup-data-hub.sh`, Sunday 04:30
  `restore-drill.sh`. Logs at `~/logs/data-hub-backup.log` +
  `~/logs/data-hub-drill.log`.
- Latest dump verified restorable. Next drill: Sunday 2026-05-31 04:30.
- Growatt UoM open items from prior STATUS (033.0024500 override,
  B710.0071401 missing ff) untouched this session.
- If next session does bulk RAR/zip ingest: `uv pip install rarfile`
  is the workaround for 7z's RAR5 partial-extract silent bug.
