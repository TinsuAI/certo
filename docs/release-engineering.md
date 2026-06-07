# Release engineering — Data Hub instance

Per-product mapping of the TinsuAI release-engineering policy onto
this repo's concrete values.

- **Policy source**: https://github.com/TinsuAI/standards (private),
  file `policies/release-engineering.md`.
- **Standards version pinned**: `v2026.05.05` (also in
  `.standards-version` at the repo root).
- **Last reconciled**: 2026-05-04 (second pass after the
  v2026.05.05 amendments).

When this file disagrees with the policy doc, the policy doc wins;
update this file. When the policy doc disagrees with reality on the
ground in this repo, that's a bug in the per-product mapping —
update this file or open a PR against `tinsu-standards` to fix the
policy.

---

## 1. Versioning

- **Scheme**: SemVer 0.x while pre-MVP. Promote to `1.0.0` at first
  paying customer go-live.
- **Current version**: `0.13.0` (in `pyproject.toml`). Bumping policy:
  increment on each tag. The jump from `0.1.0` reflects ~12 feature
  waves backfilled into `CHANGELOG.md` from git history + session
  notes (no tags were cut during the untagged pre-MVP period).
- **Tags**: first tag `v0.13.0` cut alongside the app-versioning
  feature (footer badge + `/version` + changelog page).
- **`/version` endpoint**: **DONE** (`app/main.py`). Returns
  `{app, version, git_sha, build_time, source}`; unauthenticated like
  `/healthz`. `source ∈ {build,dev,unknown}` flags whether the
  identity was baked at build time. Resolver: `app/version.py`,
  precedence env > `pyproject.toml` + `git rev-parse` > `unknown`.
- **UI surface**: footer badge on every logged-in page → `/whats-new`
  ("Có gì mới") page rendering curated `CHANGELOG.md` (Keep a
  Changelog; parser `app/changelog.py`, no markdown dep).
- **Image tags**: build-on-host, no registry. Workflow builds
  directly on the deploy runner via `docker compose up -d --build`.
  Switching to GHCR is deferred until a second deploy host enters the
  picture.
- **`pyproject.toml.version` ↔ deployed app**: **wired**. Dockerfile
  takes `VERSION`/`GIT_SHA`/`BUILD_TIME` build args → bakes to
  `DATA_HUB_*` env; `docker-compose.yml` passes them; CI deploy step
  exports them (version from `pyproject.toml`, sha from
  `git rev-parse --short HEAD`, build time UTC) before the compose
  build.

### Release process (per release)

1. Bump `version` in `pyproject.toml`.
2. Add a dated section to `CHANGELOG.md` (move `[Unreleased]` items
   down under the new `## [x.y.z] — YYYY-MM-DD`). Sections are
   user-facing Vietnamese: **Mới / Cải tiến / Sửa lỗi**. Omit
   internal-only churn (refactors, test plumbing).
3. Commit, tag `vX.Y.Z`, push `main` → auto-deploy bakes the new
   identity into the image.

## 2. Branching

- **Strategy**: GitHub Flow + tagged production releases (per
  policy).
- **Branch naming**: `feature/`, `fix/`, `chore/`, `docs/`. Already
  in use; not enforced by tooling.
- **Merge style**: rebase + fast-forward where possible; squash
  acceptable for messy feature branches.
- **Branch protection on `main`**: NOT enabled. The TinsuAI org is
  on the GitHub free plan; private-repo branch protection requires
  Pro. Enable when the org upgrades, OR if this repo is ever made
  public.
- **Approvals**: solo-maintainer; no PR approvals required today.
- **Signed commits / tags**: not adopted (deferred per policy §8).
- **Hotfix flow**: not exercised yet. Policy default applies (cut a
  release branch from the prod tag, fix there, tag a patch).

## 3. Deployment shapes

### Tier D (Demo) — LIVE

| Property | Value |
|----------|-------|
| Hosting | Single VPS — Tailscale-reachable host `tinsu` (`100.84.189.87`) |
| Public access | https://ttdatahub.tinsu.ai (Cloudflare tunnel; HTTP internally) |
| Auth | API auth disabled: `DATA_HUB_API_AUTH_DISABLED=1`; UI auth required |
| Container runtime | Docker Compose (`app` + `db`) |
| App service | `data-hub-app` on host port 8754 (single uvicorn worker) |
| DB service | `postgres:16`, named volume `pgdata` |
| File storage | Named volume `appfiles` mounted at `/var/lib/data-hub/files` |
| JWT keys | Named volume `appkeys` mounted at `/var/lib/data-hub/keys` (canonical path) |
| Demo data | C3 demo seed loaded once via scripted feed (see §4) |
| LLM | `https://codex-lb-demo.sgnai.dev/v1` (open OpenAI-compat LB) |
| Backup | Tier 1 (see §5). |
| Monitoring | None (manual `/healthz` polls). |
| Deploy trigger | Push to `main` → CI/CD self-hosted runner `data-hub-demo` (runner name `tinsu-data-hub`) |
| RTO / RPO | best-effort / 24 h |

Production-relevant env that differs from demo defaults:

- `DATA_HUB_API_AUTH_DISABLED=1`
- `DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS=https://barry-co.tinsu.ai`
- `DATA_HUB_FORCE_HTTPS_COOKIE=1`

DB-side settings that differ:

- `hub.app_settings.sso_issuer_url = https://ttdatahub.tinsu.ai`
- `hub.app_settings.sso_active_kid = k1`
- `hub.app_settings.sso_token_ttl_seconds = 600`

### Tier S (Staging) — NOT YET STOOD UP

Will be cut when the first `vX.Y.Z-rc.N` tag is on the table. May
share the `tinsu` host with Tier D under separate Compose project +
ports + volumes (see policy §3 multi-tenant rules).

### Tier P (Production) — NOT YET STOOD UP

Per-customer 1-VPS expected. First paying-customer date unknown.
Before go-live, apply the [Tier-2 backup uplift](#5-backup--restore)
and the open items in §6.

### Multi-tenant note

The `tinsu` host already runs Data Hub demo + CO demo (and
unrelated services). All are Tier D. Co-tenancy is allowed at this
tier per policy. If we ever co-tenant Tier P workloads on a single
host, the per-host isolation contract from policy §3 applies and
must be documented per-tenant.

## 4. Seed taxonomy

| Category | Source files | Behavior |
|----------|--------------|----------|
| **C1 schema** | `db/migrations/NNN_*.sql` | Append-only. Runner: `apply_migrations()` in `app/database.py`. Idempotent on filename via `hub.schema_migrations`. |
| **C2 reference** | `app/seed_master_data.py` + `data/seeds/*.yaml` | **One-shot**: seeds only when target table is empty; subsequent changes flow via C1 migrations. Conflict resolution: `on conflict do nothing`. |
| **C3 demo** | `app/seed.py` (`auto_seed_demo_if_empty`) | Gated by env `DATA_HUB_AUTO_SEED_DEMO` **at lifespan startup only**. Compose currently sets `DATA_HUB_AUTO_SEED_DEMO: "0"`, so the lifespan path is disabled. Test bootstrap in `tests/conftest.py` calls `auto_seed_demo_if_empty()` directly and intentionally bypasses the env gate (see C5 row). The current demo deploy was originally seeded via `app/seed.py` while the env gate was `"1"`; demo data has since been edited via UI. |
| **C4 customer** | UI / API only. Never seeded. | — |
| **C5 test fixtures** | `tests/conftest.py` (session autouse) + per-test fixtures | Reuses C2 + C3: `tests/conftest.py` calls `apply_migrations()` + `seed_master_data_if_empty()` + `seed_admin_if_empty()` + `auto_seed_demo_if_empty()`. **C3 doubles as C5** — Growatt/Johnson clients (and the test data their fixtures expect) are required by tests in `test_agent.py`, `test_llm_*.py`, `test_co_columns.py`, etc. |

`scripts/feed_demo_company.py` is **not** a C3 seed. It is an
offline Playwright UI driver used to generate one specific demo
company end-to-end against a live dev server, with the resulting
artifacts archived under `.ai/features/2026-05-04-demo-company-feed/`.
It does not run on the deploy host and shouldn't be classified as
a startup seed.

When schema changes require transforming existing data:

- DDL + same-migration `update` / `insert into ... select ...` is
  the pattern. See migration `010_bcct_co_columns_and_year.sql`
  for the canonical example.

## 5. Backup & restore

- **Tier**: 1 (Demo).
- **Method**: `pg_dump --format=custom` inside the `db` container,
  daily at 02:30. Driver: `deploy/scripts/backup-postgres.sh`
  (Compose-aware; wraps `docker compose exec -T db pg_dump`).
- **Schedule**: user crontab on `tinsu` (since the user lacks
  passwordless sudo, system cron at `/etc/cron.d/data-hub` isn't
  installed; the file `deploy/cron.d/data-hub` in this repo is
  preserved as the prod-with-sudo template). The user-cron entry
  on `tinsu`:
  ```
  30 2 * * * BACKUP_ROOT=/home/tinsu/backups/data-hub \
    COMPOSE_DIR=/home/tinsu/data-hub \
    /home/tinsu/data-hub/deploy/scripts/backup-postgres.sh \
    >> /home/tinsu/logs/data-hub-backup.log 2>&1
  ```
- **Location**: `/home/tinsu/backups/data-hub/*.dump` on the `tinsu`
  host (user-owned). Tier-2 uplift moves this to `/var/backups`
  with off-site shipping.
- **Retention**: 30 days local. No off-site (S3 ship block in the
  script is commented out).
- **File volumes (`appfiles`, `appkeys`)**: NOT backed up.
- **Last restore drill**: never. Will be a Tier-2-uplift action
  before the first paying customer.
- **Last verified backup run**: 2026-05-04 (manual trigger; dump
  9.9 MB; `pg_restore --list` opens cleanly).

### Restore procedure (Tier-1, Compose)

This **replaces** the systemd-era procedure that used to live in
`deploy/runbook.md`. The `tinsu` deployment runs Postgres in a
container, not on the host.

```bash
SSH=/mnt/c/Windows/System32/OpenSSH/ssh.exe   # WSL → Windows SSH
"$SSH" tinsu@100.84.189.87 bash << 'REMOTE'
set -e
cd ~/data-hub

# Pick the latest dump
LATEST=$(ls -t /var/backups/data-hub/*.dump 2>/dev/null | head -1)
[ -z "$LATEST" ] && { echo "no dump found in /var/backups/data-hub"; exit 1; }
echo "restoring from $LATEST"

# Stop the app (DB stays up)
docker compose stop app

# Drop + restore the hub schema
docker compose exec -T db psql -U hub -d data_hub -c \
  'DROP SCHEMA IF EXISTS hub CASCADE;'

# Stream the dump from host into the db container
docker compose exec -T db pg_restore -U hub -d data_hub \
  --no-owner --no-privileges < "$LATEST"

# Bring app back
docker compose up -d app
sleep 5
curl -fsS http://127.0.0.1:8754/healthz
REMOTE
```

What the dump covers and what it doesn't:

- **Covered**: all of `hub` schema (clients, users, BCCT rows,
  catalog, BOM, app_settings including SSO config, schema_migrations).
- **NOT covered**: the `appfiles` volume (uploaded Excel / PDF —
  reproducible from re-upload), the `appkeys` volume (JWT issuer
  ed25519 keypair — re-generated on first boot, but consumers will
  have to re-fetch JWKS).

If `appkeys` is lost, demo recovery is fine (boots fresh, generates
new keys). For Tier-P, the keys volume is backed up SEPARATELY per
policy §5 (post-Tier-2 action).

## 6. Open items

| # | Question | Owner | Decide by / trigger | Default if undecided |
|---|----------|-------|---------------------|----------------------|
| ~~P1~~ | ~~Implement `GET /version` + Docker build args~~ | — | **DONE** 2026-06-07 (§1) | — |
| ~~P2~~ | ~~Bump `pyproject.toml.version` to `0.2.0` and start tagging~~ | — | **DONE** 2026-06-07 — bumped to 0.13.0; tag `v0.13.0` at this release | — |
| P3 | Push image to GHCR | Maintainer | When deploying to a second host | Build on host (status quo) |
| P4 | Reconcile `deploy/runbook.md` to drop the systemd-era flow | Maintainer | Done in 2026-05-04 commit; verify no fragments left | n/a |
| P5 | Off-site backup (Tier-2 uplift) | Maintainer | Before first paying-customer go-live | Tier 1 (status quo) |
| P6 | Restore drill — first run | Maintainer | Before first paying-customer go-live | Untested |
| P7 | Branch protection on `main` (requires GitHub Pro) | Maintainer | When org upgrades plan | Off |

Cross-referenced with policy §6 open items: O1 (GHCR) ↔ P3,
O5 (staging) is not yet a decision for this repo.

## 7. Glossary references

Cross-product terms (BCCT, BQD, BTP, NVL, SP, CO, etc.) are defined
in
[`tinsu-standards/reference/glossary.md`](https://github.com/TinsuAI/standards/blob/main/reference/glossary.md).
The data-hub-specific glossary at `.ai/GLOSSARY.md` is kept for
extra terms but should not duplicate cross-product entries.
