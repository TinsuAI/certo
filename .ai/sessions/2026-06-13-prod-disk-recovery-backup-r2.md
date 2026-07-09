# 2026-06-13 — Prod/demo disk-full outage recovery + backup overhaul + R2 offsite

Started as "prod and demo are eating too much disk, propose a cleanup plan."
Turned out prod + demo had been **DOWN ~1.5 days**; the disk bloat was the
cause. Ops-only session on the remote `tinsu` box (`100.84.189.87`); no app
code touched. 5 commits to `main` (`c195f27`..`de139d4`), all deployed.

## What Was Done

**Diagnosis.** `/` at 98% (7 GB free). `docker ps -a` showed NO
prod/co/nightly containers — gone entirely (not stopped). All 4 public
endpoints 502. Volumes survived (`data-hub_pgdata`, `data-hub_appfiles`,
etc.) but showed `LINKS=0`. `nightly-build.log` had `no space left on device`
on 2026-06-12. Root cause: `data-hub_appfiles/render_cache/` (regenerable
LibreOffice PDF cache) had grown to **24.5 GB**, duplicated into
`nightly_dh_appfiles` (another 24.5 GB), and was tarred daily into backups.

**Recovery (box-side, not in git).**
- Recreated `tinsu-shared` external network (gone after the panic prune).
- Purged prod `render_cache` (24.5G→0), emptied `nightly_dh_appfiles` (28G→0),
  deleted 2 stale one-off dumps → freed 54 GB (98%→75%).
- `docker compose up -d --build` for `~/data-hub` then `~/co`; reattached
  existing data volumes. `nightly-build.sh` rebuilt demo.
- Verified: all 4 endpoints 200, CO→DH internal bridge 200.

**Recurrence fixes (committed to `main`, deployed via git pull).**
- `c195f27` — `deploy/scripts/prune-render-cache.sh` (TTL 30d + 6G LRU cap,
  cron every 6h); `backup-data-hub.sh` excludes `render_cache` from appfiles
  tar (verified 2.8G → 271M).
- `51e2239` — GFS retention (7 daily / 8 weekly-Sundays / 6 monthly-day01),
  date-based/stateless. Verified verdict logic against synthetic dates + a
  real manual backup run (PASS, pruned old artifacts correctly).
- `9f49d4d` — `backup-to-r2.sh`: offsite to Cloudflare R2 via rclone docker
  image. appfiles = incremental raw-volume sync excl render_cache (content-
  addressed ⇒ only new blobs upload); db dumps + appkeys mirror local GFS.
  Free-tier guard `R2_MAX_GB=9.5` (skip + ALARM-R2 if over). Cron 03:00.
  First real sync OK: ~6.1 GiB on R2 (appfiles 3.70G + artifacts 2.39G).
- `de139d4` — appfiles local tar → weekly (Sundays); db stays daily.
  Validated on the box (Saturday → "skip appfiles tar", PASS).

**R2 onboarding.** User created bucket `tinsu-datahub-backups` + a
bucket-scoped Object-R/W token on a personal Cloudflare account; creds written
to box-side `~/.config/rclone/rclone.conf` via a silent-prompt script (secret
never entered chat). Verified round-trip (upload/read/delete) + first sync.

**Transient verification cron.** `~/verify-old-tars-pruned.sh` (cron daily
09:00) logs how many pre-fix appfiles tars remain; raises `ALARM-PRUNE-CHECK`
if any persist past 2026-06-20 (GFS failure); self-removes (cron line + file)
once clean. Seeded: 6 old tars present now, no alarm.

## Decisions Made

- **render_cache is a pure cache** (miss → re-render from source .xls in
  `customs_declarations/`), so purge/TTL/LRU eviction is correctness-safe.
  Did NOT re-run the Jun-6 backfill, so it now regrows demand-driven (small).
- **DB vs appfiles get different retention models.** DB: small + changes
  daily + most valuable → GFS keeps a 6-month tail cheaply. appfiles:
  immutable/append-only + large → daily full tars are near-dupes, so weekly
  local + incremental R2 sync.
- **R2 sync = mirror of current state** (propagates deletions within 24h), so
  it is NOT deletion-protection; the weekly local tar is. Kept both.
- **Free-tier guard, not a hard cap** — Cloudflare R2 has no hard billing cap,
  but egress is free so worst-case is pennies; `R2_MAX_GB=9.5` skip+ALARM
  keeps storage under the 10 GB free tier.
- Secret handling: never accept tokens in chat (persisted transcript);
  silent-prompt → ssh stdin → box file.
- All ops-script changes go to `main` (the box tracks `main`); used a git
  worktree off `origin/main` each time so the user's checked-out feature
  branch stayed untouched.

## What Didn't Work

- `docker run -i ... rclone` inside an ssh heredoc **ate the heredoc stdin**,
  truncating the script mid-run. Fixed by dropping `-i` and mounting a file
  for uploads (only `rcat` needs stdin).
- `rclone lsd r2:` → 403 ListBuckets, and `copyto` → 403 CreateBucket. NOT a
  cred failure — a **bucket-scoped token** can't do account-level ops. Fixed
  by listing inside the bucket and adding `no_check_bucket = true` to config.
- bash `read -rp`/`-rsp` in the user's **zsh** → `read: -p: no coprocess`;
  pasting a long single-quoted `bash -c '...'` broke (`SK: command not found`).
  Resolved by generating a script file (`/tmp/r2setup.sh`) for the user to run.
- An autonomous "check back in a few days" cloud `/schedule` is **infeasible**:
  the box is Tailscale-only with no public SSH, so a cloud agent can't reach
  it. Used a box-side self-removing cron instead.

## Open Items

- Confirm old appfiles tars fully pruned after 2026-06-20 (self-check cron
  handles it; glance at `~/logs/verify-old-tars.log` or ask).
- Optional: delete `appfiles-2026-06-07.tar.zst` (2.8G pre-fix weekly survivor)
  to reclaim early instead of waiting ~8 weeks for GFS.
- Offsite alarms are file-based only — no push (email/Zalo) wired. Phase-2
  candidate.
- Bigger picture: the box (249 GB) hosts ~15 heavy stacks; this bought
  headroom but a dedicated box / larger disk for DH+CO is worth considering.
- Feature work on `feat/bom-material-group-declarability` (mig 079, NEEDS
  REVIEW) remains parked — untouched this session.
