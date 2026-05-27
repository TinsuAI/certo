# Project Status

**Date:** 2026-05-28 — Growatt 2026-05 data onboarded + volume mount bug fixed + backup pipeline (daily backup + weekly drill) installed on demo.

## Current State

**Branch:** `main` at `b19c88e`. **In sync with `origin/main` and demo box.**

Recent commits (this session):
- `b19c88e` — fix(deploy): align FILES_ROOT env name + add full backup + drill

Prior commits (still on HEAD, shipped earlier sessions):
- `6094e3e` — docs(handoff): BOM flat NK column + Excel export + demo deploy + audit
- `5fefa4a` — chore(bom): move Nguồn column to last position
- `9affecb` — feat(bom): NK/BOM-only column + Excel export on flat artifact page

**Tests:** 1,175 baseline (last verified 2026-05-25). This session
added no new tests; 5 pre-existing failures in
`tests/test_declarations_bulk_upload_route.py` (401 on seed login,
unrelated to session work — needs separate fix).

**Migrations:** at mig **071** (unchanged this session).

**Working tree:** clean of code drift. Same .ai/features PNGs +
untracked items as prior sessions.

**Dev server:** `:8754` running (`--workers 4`); healthz HTTP 200.

**Demo box (`100.84.189.87:8754`):** at `b19c88e`, healthz 200.
App container recreated 2026-05-28 (env fix); db container untouched.
**Files volume now wired correctly** — 2.2 GB / 4,038 blobs migrated
from container layer to `appfiles` volume.

## Growatt counts (local = demo)

```
direction | bcct_rows | distinct decls | date range
import    |    38,287 |          1,403 | 2022-11-23 → 2026-05-20
export    |       916 |            500 | 2023-11-17 → 2026-05-20

declaration_files: NK=3,538  XK=500
```

Before this session: NK 22,414/759 decls, XK 666/344 decls, decl_files 0/0.

## Backup pipeline on demo

**Daily 02:30** — `~/data-hub/deploy/scripts/backup-data-hub.sh`:
- `db-YYYY-MM-DD.dump` (~305 MB pg_dump custom)
- `appfiles-YYYY-MM-DD.tar.zst` (~167 MB compressed from 2.2 GB)
- `appkeys-YYYY-MM-DD.tar.zst` (~300 B)
- `status-YYYY-MM-DD.txt` PASS|FAIL
- `ALARM` file on failure (cleared on next PASS)
- Retention: 30 days

**Sunday 04:30** — `~/data-hub/deploy/scripts/restore-drill.sh`:
- Boots scratch `pgvector/pgvector:pg16`
- `pg_restore` newest dump
- Asserts bcct_rows>=1000, declaration_files>=1, dump_age<=2 days
- Writes `drill-YYYY-MM-DD.txt` + log line
- Last drill (manual): PASS — bcct=105,049 / files=7,259 /
  bom=13,602 / mat=13,589

Logs: `~/logs/data-hub-backup.log`, `~/logs/data-hub-drill.log`.

**Important verbiage on backup files:** `db-*.dump` is the new
naming (umbrella script). The old `YYYY-MM-DD.dump` naming from
`backup-postgres.sh` is no longer produced — old crontab entry was
removed during install. The 24 historic `2026-05-04.dump`...
`2026-05-27.dump` from the previous script remain in
`~/backups/data-hub/` and will be pruned by the new 30-day rule.

## Open Items

1. **Offsite copy** still missing. User opted local-only this
   session. Single VPS = single point of failure. Defer with
   destination choice (Cloudflare R2 / GDrive / VPS-2).

2. **ALARM file → external alert.** Currently writes to a file
   only. Wire a 1-line cron to push contents to Telegram/Zalo/email
   when it appears.

3. **Test fail in `test_declarations_bulk_upload_route`** —
   5 failures on HEAD with 401 login. Pre-existing, seed-password
   fixture issue, unrelated to this session.

4. **Collation version warning** still pending an
   `ALTER DATABASE data_hub REFRESH COLLATION VERSION` in a
   maintenance window.

5. **Growatt UoM open items from prior STATUS:**
   - `B710.0071401` raw artifact missing full_flat (1 raw uploaded
     2026-05-05 with 83 edges, never flattened).
   - `033.0024500` needs UoM override (BCCT 15 SETS / 1 PIECES vs
     catalog PIECES, code not in BOM).
   - Johnson UoM drift cleanup on 14 codes (top `1000202688`,
     `1000469803`) — agency to confirm SET-to-PIECES factors.

6. **Bulk BaoCao ingest is ad-hoc.** Inline Python with the
   `_insert_bcct` helper. Worth a `scripts/ingest_baocao.py
   --client X --nk … --xk …` so onboarding doesn't copy-paste
   `ingest_johnson_real.py` for each new client.

## Notes for Next AI Session

- **Volume bug context** — `app/storage` + `app/data_promotion`
  read `DATA_HUB_FILES_ROOT`. Compose file used to set the wrong
  name (`DATA_HUB_FILES_DIR`), causing all file uploads to land
  on the ephemeral container writable layer. **Fixed in `b19c88e`**.
  If you find file blobs at `/app/data/files` inside the container
  again, it means the fix regressed.

- **RAR5 archives + 7z 23.01 on Linux** — silent partial extract
  (only file #1). Use `uv pip install rarfile` + `RarFile.extractall`
  via system `unrar` binary.

- **Demo cron lives in `tinsu` user crontab** (not `/etc/cron.d/`).
  `crontab -l` to inspect. `/etc/cron.d/data-hub` template in
  repo is documentation-only on this host.

- **Cancel CI before destructive deploys** that involve container
  recreate — auto-deploy on push to main fires
  `docker compose up -d --build`. Use
  `gh run cancel <run-id>` if you need a window to migrate volume
  data manually first.

- **Demo seed password** in `~/data-hub/.env` on demo
  (`DATA_HUB_SEED_PASSWORD`, chmod 600). Read via
  `ssh.exe tinsu@100.84.189.87 "grep DATA_HUB_SEED_PASSWORD ~/data-hub/.env"`.

- **Per `feedback_use_windows_ssh.md`**, always use
  `/mnt/c/Windows/System32/OpenSSH/{ssh,scp}.exe` for remote ops.
