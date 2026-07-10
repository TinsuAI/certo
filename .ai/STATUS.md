# Project Status

**Date:** 2026-07-11 (late session) — **Issue #31 shipped**: alive-only default
status filter on both `/v1/hub/materials` routes (PR #38, merge `cf8ed14`),
plus a CI fix (PR #40, merge `d3ad200`): LibreOffice debs cached +
fail-fast timeouts after two 18-min apt-mirror stalls. Both deployed and
verified on prod. Session log:
`.ai/sessions/2026-07-11-issue-31-and-ci-libreoffice-cache.md`.

## Current State

- **Prod healthy — verified 2026-07-10 ~20:16Z.** `ttdatahub.tinsu.ai/version`
  → version `0.20.0`, git_sha `d3ad200`; `/healthz` → 200; anon
  `/v1/hub/dncxs` and `/v1/hub/materials` → 401. Tier-D box
  `tinsu`/100.84.189.87 (Docker).
- **#31 live:** `GET /v1/hub/materials` and get-by-code default to
  `status not in ('tombstoned','inactive')` (shared `_status_filter_sql`,
  `app/routes/api.py`); get-by-code has `?status=`; dead materials 404.
  Responses byte-identical on today's data (all rows `active`) — CO/BCQT
  unaffected. Docs: API_CONTRACT.md, API_CHANGELOG.md (2026-07-11 Additive),
  CHANGELOG.md `[Unreleased]`.
- **CI hardened (#39):** Test job caches ~90 MiB of LibreOffice debs
  (`actions/cache`, key = apt candidate version of `libreoffice-calc`);
  `timeout-minutes` 3/5 on the mirror-touching steps. Verified: hit path
  installs offline in 15s; a main-scoped cache exists (branch-scoped PR
  caches are invisible to main — main re-seeded once, expected).
- Full suite green: **1608 passed, 16 skipped** (+5 from
  `tests/test_materials_status_filter.py`).
- Dev server on :8754 may need restarting next session (see Notes recipe).

## Tracker moved to GitHub Issues (2026-07-10)

`.ai/BACKLOG.md` is **frozen**. Its 17 open items became issues #14-#35 on
`TinsuAI/data-hub`; shipped and deferred entries stay in the file as history.
New decisions go to `docs/adr/` (ADR-0001, ADR-0002 written); `.ai/DECISIONS.md`
is likewise historical. Skill config lives in `docs/agents/`. One ticket store,
no parallel paths — see `AGENTS.md` → "Agent skills — repo configuration".

## Next up — catalog redesign, order **1 → 0 → 2 → 3 → 4 → 5**

Phase 1 (#31) is **done** (this session). Remaining: **#30 → #32 → #33 →
#34 → #35**; real blocking edges 3←0, 4←3, 5←3+4. Plan + rationale:
`.ai/features/2026-07-10-catalog-candidates-merge/` (brief + design review).

- **Start here: issue #30.** One open decision inside it: placeholder config
  placement — the brief recommends `text[]` on `hub.clients`, consistent with
  existing per-client config columns.
- **#34 preservation clause:** copy the 1,207 accept decisions'
  `(decided_by, decided_at, decision_reason)` into `hub.bom_audit_events`
  before dropping `catalog_candidates`; the drop migration must enumerate
  every unreplayable column.
- **#37 (ready-for-human):** `bcct_material_identity.py:120-133` serves dead
  materials into CO's BCCT identity payload regardless of #31. Hide vs keep —
  **user decides** before anyone implements.

## Recent Changes

- `d3ad200` Merge PR #40 — `ci: cache LibreOffice debs, fail-fast timeouts`
  (`041d991`, Closes #39). Root cause: `azure.archive.ubuntu.com` throttled
  to ~40 KB/s; two 18-min Test stalls on 2026-07-10 (runs 29114048212,
  29118166424 — the latter was #38's own deploy run, cancelled + rerun).
- `cf8ed14` Merge PR #38 — `feat(api): alive-only default status filter on
  /v1/hub/materials` (`708e4bf`, Closes #31). `/code-review` ran both axes:
  Spec 0 findings; Standards 0 hard, 4 judgement calls, 2 applied.
- Previous session (2026-07-11 early): catalog plan verified, #31/#34
  amended, #37 filed, phase order settled — see
  `.ai/sessions/2026-07-11-catalog-plan-verification.md`.

## Next Steps

1. **`/implement` #30** (catalog phase 0) — branch first, commit `Closes #30`.
   Decide placeholder-config placement (brief recommends `text[]` on
   `hub.clients`) at the start.
2. **Decide #37** — dead materials in the BCCT identity payload: hide (apply
   #31's predicate) or keep deliberately (document in API_CONTRACT). User call.
3. **CO integration is unbuilt** for refresh tokens. DH side done + documented
   in `.ai/sister-app-notes/2026-07-10-sso-refresh-tokens-available.md`.
   CO is `~/workspace/client/barry-CO-main` — audit-only from this repo.
4. **Branch cleanup:** `feat/materials-alive-only-filter`,
   `ci/cache-libreoffice-debs`, `feat/sso-refresh-tokens` are merged/stale —
   safe to delete local+origin. `docs/agency-staff-guide` (`d5ae3ab`) still
   holds a 385-line VN guide that exists nowhere else — decide PR or drop.
5. **`v0.19.0` tag is absent** (`589bdae` never tagged); sequence jumps
   v0.18.0 → v0.20.0. Tag it if contiguous history matters.
6. **Postgres collation-version mismatch on prod** (DB 2.41 vs OS 2.36) —
   needs `REINDEX` + `ALTER DATABASE ... REFRESH COLLATION VERSION` in a
   maintenance window. Data-integrity investigation, not a quick reindex.
7. **Next release cut (0.21.0)** sweeps CHANGELOG `[Unreleased]` (#31 entry)
   and bumps pyproject + uv.lock together.

## Notes for Next AI Session

- **Read this file and the last 2-3 session summaries BEFORE touching
  anything.**
- **Auth surfaces are split: `/v1/auth` is public, `/v1/hub` is guarded.**
  The `api_auth_strict` dependency lives on the `/v1/hub` router
  (`app/routes/api.py`). Don't retrofit the guard onto `/v1/auth`.
- **Never widen refresh scope.** A refreshed access token returns the live ACL
  *intersected* with the grant frozen at login.
- **Single-use consume pattern** (`sso_codes.consume()`, `sso_refresh.rotate()`):
  `UPDATE ... WHERE used_at IS NULL ... RETURNING` in one transaction; raising
  rolls back. Never add a write after the raise path.
- **Error responses are centralized** — raise the right `HTTPException`, let
  `app/main.py` handlers render; translate human messages in
  `i18n.ROUTE_DETAIL_VI(_PREFIX)`. Guard: `tests/test_error_pages.py`.
- **Restarting the dev server: kill the MASTER first, then orphaned workers.**
  `pkill -9 -f "uvicorn app.main:app ... --port 8754"` → `kill -9 $(fuser
  8754/tcp)` → confirm empty before relaunch. **A bare `pkill -f 'uvicorn
  app.main:app'` also kills the calling shell (exit 144).** Don't touch :8001
  (CO dev) / :8014.
- **Background dev-server launch:** `run_in_background` Bash with
  `exec uv run uvicorn ...` (no `&`/`nohup`).
- **Real-data E2E auth on dev:** dev DB admin password is NOT `.env`'s
  `DATA_HUB_SEED_PASSWORD` after running the suite (conftest resets it).
- **Merge auto-deploys to prod:** every push to `main` runs `Deploy to tinsu`
  (incl. prod smoke through Cloudflare). Update CHANGELOG before merging;
  bump `API_CHANGELOG.md` if the sister-app surface changed.
- **After `gh pr merge`: `git fetch` then `git merge --ff-only origin/main`**
  (`pull.rebase=true` breaks `git pull --ff-only` on a dirty tree).
- **CI cache scoping:** PR-branch caches are invisible to `main`; main-scoped
  caches are visible everywhere. A "Cache not found" on main right after a PR
  seeded one is expected once. Key rotates on LibreOffice point releases
  (bump = one ~20s re-seed).
- **`gh run list --jq` does not accept jq `--arg`** (gh parses it as its own
  flag). Filter by `--commit <sha>` instead. Partial logs of an in-progress
  job 404; use the steps API for live hang diagnosis.
- **Diagnosing a "slow deploy": check which JOB and STEP first** (steps API
  shows live `started_at`). CD leg on the box is 74-100s when healthy; the
  two known stall modes are the apt mirror (now cached away) and the
  self-hosted runner dying with the box network.
- **Pre-existing dirty tree is NOT from recent sessions — leave alone:** `M`
  `.ai/BACKLOG.md`; many untracked `.ai/sessions/*`, `docs/training/*`,
  `scripts/*`.
