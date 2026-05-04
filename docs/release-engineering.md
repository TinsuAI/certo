# Release engineering & operations standards

Authoritative rules for Data Hub (and sister apps that adopt them) on
versioning, branching, deployment shapes, seed-data taxonomy, and
backup/restore. Each section opens with industry context and ends with
the project's pick. Where the pick is provisional, it's marked `[TBD]`.

> Status: **draft 2026-05-04** — agreed by user; first revision pending
> sister-app review (BCQT, CO).

References used:
- [Semantic Versioning 2.0.0](https://semver.org/)
- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/)
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
- [GitLab Flow](https://docs.gitlab.com/topics/gitlab_flow/)
- [Trunk Based Development](https://trunkbaseddevelopment.com/)
- [PostgreSQL Continuous Archiving and PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)
- 3-2-1 backup rule (US-CERT TA13-141A, widely adopted).

---

## 1. Versioning

### 1.1 Industry context

Two dominant schemes:

- **SemVer (`MAJOR.MINOR.PATCH`)** — implies API stability promise.
  MAJOR for breaking, MINOR for additive, PATCH for fixes. Pre-release
  suffix: `-rc.1`, `-beta.2`. Best when there's a public/consumer API.
- **CalVer (`YYYY.MM.PATCH` or `YY.MM`)** — used by Ubuntu, GitLab,
  Twisted. Good for continuous-delivery products with no stability
  promise.

Build identification beyond the version number:
- **Git SHA**: 7-char short SHA (`abc1234`) included in image tag,
  exposed at runtime.
- **Build timestamp**: ISO-8601 UTC.
- **Conventional Commits** enable automated CHANGELOG + version bumps
  via tooling (`commitizen`, `release-please`, `semantic-release`).

### 1.2 Project policy

**Scheme: SemVer 0.x while pre-MVP; promote to 1.0.0 at MVP launch.**

Rationale: Data Hub has a public consumer API (`/v1/hub/*`) used by CO
and BCQT. Stability promise belongs in the version number. Until MVP
ships, breaking changes are still expected, so `0.MINOR.PATCH` signals
"unstable" by SemVer convention.

**Tags & releases:**
- Git tag format: `vMAJOR.MINOR.PATCH` (e.g. `v0.4.2`).
- Tags are signed (`git tag -s`) when the maintainer has GPG set up;
  unsigned is acceptable in the demo phase.
- Each tag has a corresponding GitHub Release with notes generated
  from commit log (manual until automation lands).

**Branch ↔ deployment mapping:**
| Ref          | Image tag          | Auto-deploys to     |
|--------------|--------------------|---------------------|
| `main`       | `data-hub:main` + `data-hub:sha-<short>` | demo |
| tag `vX.Y.Z` | `data-hub:vX.Y.Z`  | production (manual) |
| feature/*    | `data-hub:sha-<short>` (build only, no deploy) | — |

**Runtime version exposure:**
- App reads `DATA_HUB_VERSION` (build-time) and
  `DATA_HUB_GIT_SHA` (build-time) from env.
- `GET /version` returns `{"version", "commit", "built_at",
  "deployment_env"}`. Public, unauthenticated, cheap.
- `/healthz` stays minimal (`{"status":"ok"}`) — used by health probes
  that want a 1-byte response.

**`pyproject.toml.version` policy:**
- Bumped on every tag.
- Source of truth for `DATA_HUB_VERSION` (Dockerfile reads it via
  build arg).

**Where the version lives at deploy time:**
- The deployed app's `/version` answers definitively.
- The git ref is recorded in the GitHub Actions run log (deploy job
  prints `git rev-parse HEAD`).
- `docker compose ps` + `docker inspect data-hub-app-1` show the
  image digest; cross-reference with the registry tag.

### 1.3 Open questions

- Whether to mirror images to a registry (Docker Hub / GHCR) or stay
  build-on-server. Recommendation: ship to GHCR once we have a
  multi-host deploy. **[TBD]**
- Whether to adopt Conventional Commits + `release-please` for
  automated bumps. Recommendation: yes after first 1.0.0. **[TBD]**

---

## 2. Branching strategy

### 2.1 Industry context

- **Trunk-based development**: everything on `main`, feature flags
  for in-progress work. Highest velocity, requires discipline + flag
  hygiene. Used by Google, Facebook.
- **GitHub Flow**: `main` + short-lived branches → PR → merge.
  Simplest for small teams shipping continuously.
- **GitLab Flow with environment branches**: `main` + named env
  branches (`production`, `staging`); merges flow forward. Useful
  when you need to deploy *older* code to specific environments.
- **Git Flow** (Driessen): `develop`, `master`, `release/*`,
  `feature/*`, `hotfix/*`. Heavy; out of fashion for continuous
  delivery products.

### 2.2 Project policy

**GitHub Flow + tagged production releases.**

- `main` is **always deployable**. CI must be green for a merge to
  succeed.
- Branch naming:
  - `feature/<short-slug>` — new functionality
  - `fix/<short-slug>` — bug fix
  - `chore/<short-slug>` — tooling, refactors, no behavior change
  - `docs/<short-slug>` — docs only
- Branches are short-lived (target: ≤ 5 days). Long-running work goes
  behind a feature flag, not a long branch.
- Direct commits to `main` are allowed for trivial fixes (typos,
  comment edits) by the user themself; PRs preferred for everything
  else.
- **No `develop` branch.** No `release/*` branches. No `hotfix/*`
  branches — emergencies use the same `fix/*` flow as routine bugs.

**Merge style:** rebase + fast-forward, OR squash-merge for
multi-commit feature branches with messy history. Avoid merge
commits on `main` — keeps the log linear and `git bisect` clean.

**Environment ↔ ref mapping:**
- Demo deploys `main` on every push (current setup, see
  `.github/workflows/ci-cd.yml`).
- Production deploys ONLY tagged releases via
  `workflow_dispatch` with `version` input. Operator types
  `v0.5.0` to deploy that tag. **[TBD when prod stands up]**
- Staging (when introduced): deploys tagged release candidates
  (`v0.5.0-rc.1`).

**Forbidden:**
- Force-push to `main` (use branch protection).
- Deploying a feature branch to production.
- Deploying an untagged commit to production (CI/CD must reject).

**Hotfix flow** (future, when prod exists):
1. Branch `fix/<slug>` from the tag currently on prod (e.g.
   `git checkout -b fix/bom-crash v0.5.0`).
2. Fix + tests + PR to `main`.
3. After merge, cut a new patch tag (`v0.5.1`) on `main` if `main`
   has no other un-released changes; otherwise cherry-pick onto a
   dedicated patch branch and tag from there.

### 2.3 Open questions

- Whether to require signed commits on `main`. Recommendation: enable
  GitHub branch protection requiring signed commits once core
  contributors all have GPG/SSH-signing set up. **[TBD]**
- Whether to require approvals on PRs to `main`. Recommendation:
  1 approver from a different role for production-bound changes,
  no approvals required for demo-only churn (UI tweaks etc.).
  **[TBD]**

---

## 3. Deployment shapes

Three target shapes. Each has a different rigor / cost tier. The
"three deployment shapes per agency" mentioned in `AGENTS.md` is a
**product** taxonomy (which apps an agency runs); this section is
about the **operational** deployment shape (demo vs prod).

### 3.1 Demo (current)

**Target:** internal show-and-tell to prospective customers + sister
apps integration testing.

| Property | Value |
|----------|-------|
| Hosting | Single VPS (`tinsu`) |
| Public access | Cloudflare tunnel → `https://ttdatahub.tinsu.ai` |
| TLS | Terminated at Cloudflare; tunnel is HTTP internally |
| Container runtime | Docker Compose (`app` + `db`) |
| Postgres | `postgres:16` containerized, named volume `pgdata` |
| File storage | Named volume `appfiles` (LocalFS) |
| JWT keys | Named volume `appkeys`, generated on first boot |
| Auth | API auth disabled (`DATA_HUB_API_AUTH_DISABLED=1`) |
| Demo data | `auto_seed_demo_if_empty` enabled OR restored from `data/seed/demo.dump` once |
| LLM | Pointed at `https://codex-lb-demo.sgnai.dev/v1` |
| Backup | Daily `pg_dump` via cron, local-only, 30-day retain |
| Monitoring | None (manual `gh run list` + `/healthz`) |
| Deploy trigger | Push to `main` → CI/CD self-hosted runner `data-hub-demo` |
| RTO | best-effort (operator on call) |
| RPO | 24 h |

```
┌──────────────────┐  HTTPS   ┌────────────────────┐  http     ┌───────────┐
│  customer demo   │ ───────▶ │  Cloudflare edge   │ ─────────▶│ tinsu VPS │
│  (browser)       │ TLS      │  (tunnel ingress)  │ tunnel    │           │
└──────────────────┘          └────────────────────┘           └─────┬─────┘
                                                                     │
                                            ┌────────────────────────┼─────────────────┐
                                            │  docker compose                          │
                                            │  ┌──────────────┐    ┌──────────────┐    │
                                            │  │  app:8754    │◀──▶│  db:5432     │    │
                                            │  │  (uvicorn)   │    │  (postgres   │    │
                                            │  │              │    │   :16)       │    │
                                            │  └──────┬───────┘    └──────┬───────┘    │
                                            │         │                   │            │
                                            │  vol: appfiles       vol: pgdata         │
                                            │  vol: appkeys                            │
                                            └──────────────────────────────────────────┘
                                                          │
                                                cron 02:30 daily
                                                          ▼
                                                /var/backups/data-hub/*.dump
                                                (30-day retain, local only)
```

### 3.2 Staging (proposed) **[TBD]**

**Target:** rehearse production deploys before tagging. Pre-flight
for release candidates.

Differences from demo:
- Auth strict mode on (`api_auth_strict=true`).
- `DATA_HUB_AUTO_SEED_DEMO=0`. No demo data; staging data is
  hand-curated to mirror a representative customer.
- Off-site backups (S3-compat).
- Deploys release candidates (`v*-rc.*` tags) not `main`.
- Same VPS as demo OR dedicated; for cost, share VPS with separate
  Postgres DB + ports.

### 3.3 Production (proposed) **[TBD]**

**Target:** live agency customers in regulated workflows.

| Property | Value |
|----------|-------|
| Hosting | Per-customer 1-VPS (matches CLAUDE.md product taxonomy) |
| Public access | Per-customer subdomain or customer-private DNS |
| TLS | Caddy or nginx + Let's Encrypt; OR Cloudflare tunnel |
| Container runtime | Docker Compose, same shape as demo |
| Postgres | Containerized OR dedicated Postgres server (VPS-RAM-dependent) |
| File storage | LocalFS day 1, S3-compat phase 2 (TT 39/2018 retention) |
| JWT keys | Generated once on first boot, **backed up off-site** |
| Auth | `DATA_HUB_API_AUTH_DISABLED=0`, `api_auth_strict=true` |
| Demo data | NEVER seeded (`DATA_HUB_AUTO_SEED_DEMO=0`) |
| LLM | Customer-controlled (own OpenAI/Anthropic key OR none) |
| Backup | Daily pg_dump + WAL archiving + off-site S3-compat |
| Monitoring | External `/healthz` poll (UptimeRobot, Healthchecks.io); container restart on failure |
| Deploy trigger | `workflow_dispatch` with version input → tagged release only |
| RTO | 4 h (manual restore from latest backup) |
| RPO | 1 h (WAL archive cadence) |

**What changes vs demo (concrete):**
- `.env` differences, summarized:
  - `DATA_HUB_API_AUTH_DISABLED=0`
  - Add `DATA_HUB_VERSION` + `DATA_HUB_GIT_SHA` + `DATA_HUB_DEPLOYMENT_ENV=production`
  - LLM keys: customer-supplied or omitted entirely
  - SSO config: real customer-facing domain
- `hub.app_settings` differences:
  - `api_auth_strict = true`
  - `sso_issuer_url = https://<customer-domain>`
- Caddy/nginx config in `deploy/caddy/` or `deploy/nginx/` (already
  scaffolded in `deploy/nginx/`).
- Backup cron set up by `deploy/cron.d/data-hub` + S3 ship enabled.

### 3.4 Promotion path

```
feature/* ──┐
            │ PR
            ▼
          main ──────► demo (auto, every push)
            │
            │ tag vX.Y.Z-rc.N
            ▼
          staging ──── (manual workflow_dispatch)
            │
            │ tag vX.Y.Z (after RC sign-off)
            ▼
          production ── (manual workflow_dispatch, per-customer)
```

---

## 4. Seed-data taxonomy

Seeds confuse fast because "data" covers a lot. Five disjoint
categories below, each with its own change rules. Don't mix them.

### 4.1 Five categories

| Category | Lives in | Change semantics | Lifecycle |
|----------|----------|------------------|-----------|
| **1. Schema (DDL)** | `db/migrations/NNN_*.sql` | Append-only. NEVER edit applied migration. Add new file with higher number. | Same lifetime as the app version that introduces it |
| **2. Reference / system data** | `app/seed_master_data.py` (+ YAML in `app/seed_data/`) | Idempotent on every boot. INSERT...ON CONFLICT DO UPDATE. New row = code change. Update existing = code change. Delete = explicit migration. | Lives forever; updates with code |
| **3. Demo data** | `app/seed.py` (`auto_seed_demo_if_empty`) + `scripts/feed_demo_company.py` | Runs only when DB has no clients. Skip in production via `DATA_HUB_AUTO_SEED_DEMO=0`. | Demo / staging only |
| **4. Customer (operational) data** | Created via UI / API. Lives in production DB only. | NEVER seeded. NEVER in git. | Customer's lifetime; survives version upgrades via migrations |
| **5. Test fixtures** | `tests/fixtures/*` + per-test `setup_*` fixtures in `tests/test_*.py` | Per-test scope. May reset DB between tests. | Test runtime only |

**The categories MUST stay separate.** Mixing causes:
- Customer data lost on re-seed (cat 3 overwriting cat 4).
- Reference data drift between environments (cat 2 not idempotent).
- Tests that pass locally because the dev DB has demo data, fail in
  CI because it doesn't (we hit this — see `tests/conftest.py`).

### 4.2 Change rules per category

**Cat 1 (schema):**
- New file `db/migrations/NNN_<slug>.sql`. NNN = next sequential
  integer.
- Idempotent (`create table if not exists`, `add column if not
  exists`).
- ONE logical change per file. Don't bundle.
- DDL + data fix-ups in the same migration are OK (see migration
  010 back-fill).
- Once merged + tagged, the file is **frozen forever**. To change a
  past migration's effect, write a new migration that compensates.

**Cat 2 (reference):**
- Source of truth is the YAML / Python in repo.
- Adding a row: just add to the source; idempotent insert applies it
  on next boot.
- Updating an existing row's payload: write a migration that does
  the update (because seed code only inserts on conflict-do-nothing
  by default — verify per-table). Or change `seed_master_data.py` to
  use `on conflict do update set ...` for fields that should
  re-converge.
- Deleting a row: migration with explicit `delete` + remove from
  source.
- **Verify reference seed is idempotent** before relying on it.
  Test: boot a populated DB twice; row counts shouldn't change.

**Cat 3 (demo):**
- Code-defined, not binary dumps. Easier to diff in PRs.
- Existing `data/seed/demo.dump` (10MB, gitignored) is the legacy
  approach. **Phase out** in favor of running
  `scripts/feed_demo_company.py` against an empty DB.
- Demo dumps tied to a schema version: if you must use a binary dump,
  name it `demo-vX.Y.Z.dump` and document the schema version it was
  generated against. A dump older than current schema requires either
  regenerating or applying migrations on top of the restored data.
  Fragile — prefer code seeds.

**Cat 4 (customer):**
- Never serialize. Never check into git. Never ship in container
  image.
- Migrate forward via cat-1 migrations only.

**Cat 5 (test fixtures):**
- `tests/conftest.py` runs cat-1 migrations + cat-2 reference seed +
  a single dev admin + cat-3 demo seed once per session.
- Per-test fixtures (autouse) reset only the rows they're about to
  insert (UPSERT pattern, not `truncate`).

### 4.3 Migration of customer data on schema change

When a schema change requires transforming existing customer rows
(rename column, normalize values, split into a new table, etc.):

1. Write the DDL migration first (`alter table`, `create table`).
2. In the **same** migration file, write the `update` / `insert
   into ... select ...` to populate the new structure.
3. Make the DDL nullable/permissive at first; fill in; then add
   constraints in a follow-up migration.
4. Test on a copy of demo data + (when prod exists) a copy of a
   customer DB. Verify row counts pre/post + spot-check.
5. Document in the migration's leading comment + cross-link in
   `.ai/DECISIONS.md` if non-trivial.

Example pattern:
```sql
-- 028_split_addresses.sql
-- Splits hub.clients.address into structured fields.

alter table hub.clients
  add column if not exists street text,
  add column if not exists city text,
  add column if not exists province text;

update hub.clients
  set street = split_part(address, ',', 1),
      city = split_part(address, ',', 2),
      province = split_part(address, ',', 3)
  where address is not null
    and street is null;

-- Address column kept; remove in a later migration after consumers update.
```

---

## 5. Backup & restore

### 5.1 Industry context

- **3-2-1 rule**: 3 copies, 2 different media/storage classes, 1
  off-site. Origin: US-CERT.
- **RTO** (Recovery Time Objective): max acceptable downtime to
  restore service.
- **RPO** (Recovery Point Objective): max acceptable data loss
  measured in time.
- **Test restores periodically** — un-tested backups are not
  backups. Quarterly minimum; monthly preferred.
- **Postgres-specific:**
  - `pg_dump --format=custom` — logical, portable across major
    versions, slow on very large DBs.
  - `pg_basebackup` + WAL archiving — physical, point-in-time
    recovery. More setup; granular RPO (seconds).
  - Streaming replica — hot-standby; near-zero RPO/RTO at the cost
    of a second machine.

### 5.2 Project policy

**Two tiers, matching deployment shapes.**

#### Tier 1 — Demo

| Property | Value |
|----------|-------|
| Method | `pg_dump --format=custom` |
| Frequency | Daily 02:30 (cron) |
| Retention | 30 days local |
| Off-site | None |
| File volume | Not backed up (demo files are reproducible) |
| Test restore | None scheduled (verify dump opens via `pg_restore --list`) |
| RPO | 24 h |
| RTO | best-effort |

Already implemented in `deploy/scripts/backup-postgres.sh` +
`deploy/cron.d/data-hub`. Verify the cron is active on the server:
```
crontab -l    # if installed for the user
ls /etc/cron.d/data-hub    # if installed system-wide
```

#### Tier 2 — Production **[TBD when first customer ships]**

| Property | Value |
|----------|-------|
| Method | `pg_dump` daily + WAL archive every 5 min OR streaming replica (decide per customer SLA) |
| Frequency | Daily base + 5-min WAL increments |
| Retention | 7 daily + 4 weekly + 12 monthly |
| Off-site | S3-compatible (Cloudflare R2 or MinIO), encrypted |
| File volume | Daily `tar` of `appfiles` volume → off-site |
| Keys volume | Off-site backup ONCE on first generation; stored in a separate vault from data backups |
| Test restore | Quarterly: spin up a scratch VPS, restore latest, run smoke suite, tear down |
| RPO | 1 h |
| RTO | 4 h (single-VPS) |

**Concrete actions before the first prod ships:**
1. Uncomment the S3 ship block in
   `deploy/scripts/backup-postgres.sh` and parameterize endpoint /
   bucket / credentials via `/etc/data-hub/.env`.
2. Add `deploy/scripts/backup-files.sh`: tar `/var/lib/data-hub/files`
   → S3-compat. Schedule via cron at 03:00.
3. Add WAL archive config to Postgres (`archive_mode = on`,
   `archive_command = '/usr/local/bin/wal-ship.sh %p'`). The script
   ships to S3-compat.
4. Add `deploy/scripts/restore-test.sh` — runs in a scratch
   container, downloads latest dump, restores, hits `/healthz`,
   asserts row counts. Optionally invoke via GitHub Actions on a
   monthly schedule.
5. Document runbook entry for "Disaster recovery: VPS dead". The
   procedure needs concrete commands, not "you know what to do".

### 5.3 Restore procedure (current demo)

Already documented in `deploy/runbook.md` → "Postgres restore drill".
Summary, in Docker Compose form:

```bash
cd /home/tinsu/data-hub

# Stop the app (don't stop db; restore needs it)
docker compose stop app

# Pick the latest dump
LATEST=$(ssh tinsu@... 'ls -t /var/backups/data-hub/*.dump | head -1')

# Drop + restore the hub schema
docker compose exec -T db psql -U hub -d data_hub -c \
  'DROP SCHEMA IF EXISTS hub CASCADE;'
docker compose exec -T db pg_restore -U hub -d data_hub \
  --no-owner --no-privileges < "$LATEST"

# Bring app back up
docker compose up -d app
sleep 5
curl -fsS http://127.0.0.1:8754/healthz
```

For the production tier procedure, see TBD section 5.2 above.

### 5.4 What about the JWT keys?

`/var/lib/data-hub/keys` (the `appkeys` volume) holds the ed25519
issuer keypair. Losing it means:
- All issued JWTs become unverifiable until consumers re-fetch the
  rotated public key from JWKS (≤10 min cache TTL).
- Demo: minor — just regenerate.
- Production: severe if consumers haven't seen the new public key —
  active sessions break, service-to-service auth fails.

**Policy:**
- Demo: not backed up. Re-generate on restore.
- Production: backed up ONCE on first generation, off-site, encrypted
  at rest with a different key than the data backups. Document the
  recovery flow separately so a single compromised storage account
  can't expose both.

---

## Appendix A — Implementation checklist (incremental)

### A.1 Quick wins (do soon)
- [ ] Add `GET /version` endpoint reading `DATA_HUB_VERSION` +
      `DATA_HUB_GIT_SHA` env.
- [ ] Pass `VERSION` + `GIT_SHA` as Docker build args; embed in
      image; expose via env in `docker-compose.yml`.
- [ ] Add `release-engineering.md` cross-link in `AGENTS.md`.
- [ ] Bump `pyproject.toml` to a real pre-MVP version (e.g.
      `0.1.0` → `0.2.0` after this doc lands).

### A.2 Before first production customer
- [ ] Cut `v1.0.0-rc.1` tag.
- [ ] Stand up staging deployment shape (section 3.2).
- [ ] Implement Tier-2 backup pipeline (section 5.2 actions 1–5).
- [ ] Add `workflow_dispatch` deploy job that requires a `version`
      input matching a tag.
- [ ] Branch protection on `main`: require CI green, require linear
      history, no force-push.
- [ ] First customer's deployment runbook (per-customer addendum to
      `deploy/docker-deploy.md`).

### A.3 Optional / nice-to-have
- [ ] Conventional Commits + `release-please` for automated CHANGELOG.
- [ ] GHCR image push on tag.
- [ ] Streaming Postgres replica (instead of WAL ship) for tighter
      RPO if customer SLA demands.
- [ ] External monitoring (UptimeRobot, Healthchecks.io).

---

## Appendix B — Glossary

- **RTO** — Recovery Time Objective. Max time from incident to
  service restored.
- **RPO** — Recovery Point Objective. Max acceptable data loss,
  expressed in time (e.g. "1 h RPO" = at most 1 h of data may be
  lost).
- **SemVer** — Semantic Versioning 2.0.0.
- **CalVer** — Calendar Versioning.
- **WAL** — Write-Ahead Log (Postgres). Archive these to enable
  point-in-time recovery.
- **3-2-1** — Backup rule: 3 copies, 2 storage classes, 1 off-site.
- **PITR** — Point-in-Time Recovery. Restore Postgres to any moment
  within the WAL archive window.
