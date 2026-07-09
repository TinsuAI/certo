# Project Status

**Date:** 2026-07-10 — Session shipped **SSO refresh tokens** (silent
access-token renewal for CO) and fixed a pre-existing **multi-worker bug in
`/v1/auth/exchange`**. Built → tested → mutation-tested → live-verified →
PR #13 → released `v0.20.0` → merged → deployed. Now on branch `main`, synced
to `origin/main`.

## Current State

- **Prod healthy** — `ttdatahub.tinsu.ai/version` → version `0.20.0`, git_sha
  `c4a70b3`. Tier-D box `tinsu`/100.84.189.87 (Docker). Verified live, not from
  CI logs: `/v1/auth/refresh` → `401` on a bogus token (a 401 rather than a 500
  proves the row lookup reached the DB), `400` on missing body; anon
  `/v1/hub/dncxs` → `401`. Confirmed by `psql` on the host that migs `088`+`089`
  are in `hub.schema_migrations` and both tables exist.
- **Silent renewal shipped.** `POST /v1/auth/exchange` also returns an opaque
  `refresh_token`; new `POST /v1/auth/refresh` trades it for a fresh access
  token with no bearer and no user interaction. Access token unchanged: EdDSA,
  JWKS-verifiable, `expires_in: 600`.
- **Refresh-token semantics** (`app/stores/sso_refresh.py`, mig 088): only
  `sha256(token)` stored; rotating single-use; sliding 12h idle under a hard 7d
  absolute ceiling, both capped by the bound SSO session (logout revokes);
  replay past a 30s grace window revokes the whole family; scope never broadens
  (live ACL ∩ grant frozen at login, RFC 6749 §6).
- **One-time SSO codes are Postgres-backed** (`app/stores/sso_codes.py`,
  mig 089). `_SSO_CODES` (the per-process dict) is gone.
- Full suite green: **1603 passed, 16 skipped**. Dev server running on :8754
  (`--workers 4`, no reload).

## Recent Changes

- `c4a70b3` Merge PR #13 (feat/sso-refresh-tokens).
- `e04718a` chore(release): 0.20.0 — also realigned `uv.lock` (see Notes).
- `7cdede1` docs(auth): API_CONTRACT + API_CHANGELOG + sister-app note for CO.
- `b944de0` fix(auth): one-time SSO codes → Postgres (mig 089). Measured:
  `/exchange` failed **2/12** at `--workers 4` before, **24/24** after.
- `0d8c126` feat(auth): refresh-token flow (mig 088) + `tests/test_sso_refresh.py`
  (34) and later `tests/test_sso_codes.py` (8).
- Session log: `.ai/sessions/2026-07-10-sso-refresh-tokens.md`.

## Next Steps

1. **CO integration is unbuilt.** DH's side is done and documented in
   `.ai/sister-app-notes/2026-07-10-sso-refresh-tokens-available.md`. CO stores
   the refresh token httponly (separate from its access-token cookie), adds its
   own `/auth/refresh` route + a keep-alive timer at **~T-120s** (600s TTL, 60s
   verify leeway), serializes refreshes, retries the guarded call once on `401`.
   CO is `~/workspace/client/barry-CO-main` — audit-only from this repo.
2. **`v0.19.0` tag is absent.** `589bdae` is the release commit but was never
   tagged; sequence is `v0.15.0 … v0.18.0, v0.20.0`. Tag it if contiguous
   history matters.
3. **Postgres collation-version mismatch on the prod host** — DB created with
   collation 2.41, OS provides 2.36. Silently corrupts text-column index
   ordering. Needs `REINDEX` + `ALTER DATABASE data_hub REFRESH COLLATION
   VERSION` in a maintenance window. Data-integrity investigation, not a quick
   reindex. **Unrelated to this session's change.**
4. **Answer CO's open question** (PR #11, still open): do dossiers ever contain
   embedded raster scans (operator-uploaded scanned PDFs via `file_kind=pdf`)?
   If never, `compact` lossless is final; if yes, add an image-downsample profile.
5. **`docs/agency-staff-guide` branch still unpushed/unmerged** (commit
   `d5ae3ab`) — holds a 385-line Vietnamese guide that exists nowhere else.
   Decide: open a PR or leave it. Carried over from 2026-06-19.
6. **`feat/sso-refresh-tokens` branch** exists locally and on origin; safe to
   delete.

## Notes for Next AI Session

- **Read this file and the last 2-3 session summaries BEFORE touching
  anything.** Last session skipped that and re-learned two traps below the hard
  way (the `pkill` one and the `pull.rebase` one), both already documented here.
- **Auth surfaces are split: `/v1/auth` is public, `/v1/hub` is guarded.** The
  `api_auth_strict` dependency lives on the `/v1/hub` router (`app/routes/api.py`),
  so `/v1/auth/refresh` correctly needs no bearer even with strict on in prod.
  Don't retrofit the guard onto `/v1/auth`.
- **Never widen refresh scope.** A refreshed access token returns the live ACL
  *intersected* with the grant frozen at login. If CO asks for grants to land
  without a re-login, that is a deliberate contract change — not a bug.
- **Single-use consume pattern.** Both `sso_codes.consume()` and
  `sso_refresh.rotate()` rely on `UPDATE ... WHERE used_at IS NULL ... RETURNING`
  inside one transaction for exactly-one-winner semantics, and on raising to
  roll back when a later check fails (403, redirect_uri mismatch). Adding a
  write *after* the raise path will silently lose it — that bug was hit and
  fixed once already (`_ReplayDetected` → `_revoke_family_tx`).
- **Don't trust a green concurrency test.** It passes when the requests never
  overlap. Mutation-test the guard (delete `and used_at is null`, confirm the
  test goes red) and race it over real HTTP across workers.
- **Error responses are centralized — don't add per-route error pages or manual
  `/login` bounces.** Raise the right `HTTPException` status and let the central
  handler in `app/main.py` render it. New JSON surface → put it under `/v1/` or
  `/api/v1/`. New human message → translate in `i18n.ROUTE_DETAIL_VI(_PREFIX)`,
  not inline at the raise site. Test guard: `tests/test_error_pages.py`. Memory:
  `project_central_error_handlers`.
- **Restarting the dev server: kill the MASTER first, then the orphaned
  workers.** `--workers 4` spawns workers whose cmdline is
  `python -c "from multiprocessing.spawn import spawn_main..."` — `pkill -f
  "uvicorn ... port 8754"` only hits the master, leaving orphan workers (PPID
  reparented to init) that keep holding :8754 and serving STALE code. Recipe:
  `pkill -9 -f "uvicorn app.main:app ... --port 8754"` → then `kill -9 $(fuser
  8754/tcp)` for the orphans → confirm `fuser 8754/tcp` empty before relaunch.
  **In this harness a bare `pkill -f 'uvicorn app.main:app'` also kills the
  calling shell (exit 144).** Don't touch :8001 (CO dev) / :8014.
- **Background dev-server launch:** run uvicorn as a `run_in_background` Bash
  task with `exec uv run uvicorn ...` (no `&`/`nohup`); the harness keeps it
  alive across turns. `nohup ... &` inside a backgrounded task gets killed with
  the task's process group.
- **Real-data E2E auth on dev:** the dev DB admin password is **not** `.env`'s
  `DATA_HUB_SEED_PASSWORD` — running the suite makes `tests/conftest.py` reset it
  to the test-canonical value. Either use that, or `auth.create_session(user_id)`
  + cookie, or a service token. `api_auth_strict=false` on dev but Bearer
  `/v1/hub` still 401s without a token.
- **Merge auto-deploys to prod:** the CI/CD `Deploy to tinsu` job runs on every
  push to `main` (and `workflow_dispatch`), so merging a PR ships to
  `ttdatahub.tinsu.ai` (incl. a prod smoke through Cloudflare) and applies
  pending migrations at container boot. Update CHANGELOG before merging; bump
  `API_CHANGELOG.md` if the sister-app API surface changed.
- **After `gh pr merge`: `git fetch` then `git merge --ff-only origin/main`** —
  the repo has `pull.rebase=true`, so `git pull --ff-only` errors with "cannot
  pull with rebase" when the tree has unstaged changes. `git merge --ff-only`
  preserves them.
- **`uv.lock` drift is FIXED** (supersedes the old note here). It had declared
  `data-hub 0.13.1` while `pyproject` moved through `0.19.0`; the `0.20.0`
  release regenerated it — one line, no dependency resolution changed. Releases
  may now bump `pyproject.toml` + `CHANGELOG.md` + `uv.lock` together.
- **Pre-existing dirty tree is NOT from recent sessions — leave alone:** `M`
  `.ai/BACKLOG.md`; many untracked `.ai/sessions/*`, `docs/training/*`,
  `scripts/*`.
