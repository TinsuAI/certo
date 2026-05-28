# Project Status

**Date:** 2026-05-29 — closed BACKLOG A.1 the cheap way (dead-column
drop, not the planned cross-cut refactor) after data audit showed
zero in-use overrides.

## Current State

**Branch:** `main` at `79ae85a`. **In sync with `origin/main` and demo box.**

Recent commits (newest first):

- `79ae85a` — feat!(catalog): drop unused materials.category_override + override_reason
- `b7f5081` — feat!(bom-api): drop BOM vocab v1 URL aliases (308 → 404)
- `ec528ed` — docs(handoff): CO API trio + quality fixes session
- `316ec57` — feat(bom-api): picker filters on `/bom/artifacts`
- `28ea610` — feat(declarations-api): Bearer mirror of declarations ZIP

**Tests:** **1,260 passed, 15 skipped** (verified 2026-05-28
post-mig-072 ship; baseline unchanged — schema-only drop, no
behaviour change).

**Migrations:** at mig **072**.

**Dev server:** `:8754` running with new code; healthz HTTP 200.

**Demo box (`100.84.189.87:8754`):** at `79ae85a`, healthz 200.
CI auto-deployed (~1.5 min). Demo DB confirmed columns dropped;
`hub.materials` no longer has `category_override` / `override_reason`.

## Recent Changes (last session)

A.1 BACKLOG closure — but **not** the way the BACKLOG plan suggested.
Original plan: replace single `category` + `category_override` patch
with multi-role `roles[] text[]`, ~2-3 days cross-cut refactor.

Discovery 2026-05-28 found:
- `category_override` + `override_reason` (mig 002 scaffold,
  2026-05-01) were a "patch instead of edit" design from before
  mig 045 audit trigger + A.3 edit form supplanted them. The UI
  to set overrides was never built (session 2026-05-01 to-do #11,
  dropped on the floor).
- Local dev DB audit: **0/13,589 rows** across Growatt + Johnson
  have either column set. Dead architecture, not active hack.
- `observed_roles[]` (mig 046) already surfaces multi-role truth at
  view level — declared multi-role would only resolve 1 conflict
  out of 13,589.

Mig 072 + 6-callsite refactor shipped in ~35 min instead of 2-3
days. Phase 3 declared multi-role deferred until concrete staff
workflow blocker appears. Files: `db/migrations/072_drop_category_override.sql`,
`app/routes/{catalog,api}.py`, `app/resolvers/bcct_material_identity.py`,
`app/templates/clients/catalog_{detail,conflicts}.html`,
`docs/API_CONTRACT.md`, `docs/API_CHANGELOG.md` (Breaking entry),
`.ai/BACKLOG.md` (A.1 marked CLOSED with rationale),
`.ai/features/2026-05-28-catalog-roles-array/brief.md` (discovery doc).

Memory updated: `project_bom_code_multirole.md` notes mig 072 + the
view-level surfacing supersedes the originally-planned column-level
fix.

## Next Steps

1. **F.1 Growatt BOM wipe + re-ingest** — still pending per
   `project_reingest_pending.md`. Hygiene only; defer unless surface
   pain appears.
2. **A.4.3 follow-up if needed** — current normalize-then-bucket
   gives 21% noise reduction on Johnson per-product codes. Only
   worth more work if staff complain.
3. **D.1 Aggregate-data git-history** — large principle work
   (materials/code_mappings/client_config history tables + revert UI).
   Needs `/discover` first.
4. **STATUS open items unchanged** — offsite backup missing
   (single VPS = SPOF); ALARM file → external alert (user passed
   on this one explicitly).

## Notes for Next AI Session

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
