# Project: Data Hub (provisional)

## Session Start

Read `.ai/STATUS.md` and last 2-3 session summaries in `.ai/sessions/` before doing anything. Cross-repo context lives in `~/workspace/client/BCQT-System/.ai/DECISIONS.md` — see "2026-04-30 PM — Data Hub 3-app architecture" entry for the canonical decision history.

## Overview

**Vendor:** Tinsu AI (bespoke software solutions company).
**Product:** Data Hub — agency master records management. One of three Tinsu AI products serving customs compliance agencies.
**Status:** Pre-MVP scaffold (2026-04-30). No code yet. Awaiting M9 discovery sprint.

**Naming:** "Data Hub" is provisional working name. Marketing/branding name not yet locked. Repo path + Postgres schema names may rename later.

## Three Tinsu AI products (locked 2026-04-30 PM)

1. **Data Hub** *(this repo)* — master records management. Owns shared HQ-data tier (BCCT + Danh Mục NVL/SP/BTP + BOM in MVP; file snapshots phase 2).
2. **BCQT-System** (`~/workspace/client/BCQT-System`) — annual settlement reports (Mẫu 15 / 15a / 16). Read-only consumer of Data Hub.
3. **CO-System** (`~/workspace/client/barry-CO-main`) — origin certificates per-shipment. Read-only consumer of Data Hub for HQ-data; writes per-shipment BCCT to Data Hub via API.

## Architecture (3-app, hybrid storage)

```
deployment/
├── postgres
│   ├── hub schema      ← OWNED by Data Hub (writes); other apps read-only
│   ├── bcqt schema     ← OWNED by BCQT
│   └── co schema       ← OWNED by CO
├── projects/
│   └── project_<id>.db ← BCQT per-project SQLite (settlement, findings, pipeline_runs, data_files)
├── files/              ← LocalFS day 1, S3-compat phase 2
└── 3 process: hub + bcqt + co
```

**Strict ownership rules (Postgres role-per-app):**
- Data Hub writes `hub` schema only. All HQ-data writes (Excel upload, CO-via-API) flow through Data Hub.
- BCQT writes `bcqt` schema + per-project SQLite only. Pure read-only consumer of `hub`.
- CO writes `co` schema only. Per-shipment BCCT writes call Data Hub API (no direct DB write to `hub`).

**Engine:** Hybrid Postgres + per-project SQLite. Postgres for shared schemas, SQLite stays for BCQT project-truly-local.

**Auth:** SSO via internal auth center hosted in Data Hub (not Keycloak/Authentik — avoid third-party dep at current scale).

## MVP scope

**Structured tier only:**
- BCCT (customs declarations) — parse Excel + storage + read API for consumers
- Danh Mục (material registry — NVL/SP/BTP) — parse Excel + storage + versioning + read API
- BOM (bill of materials) — parse Excel + versioning + read API
- SSO + auth center
- Write API for CO per-shipment BCCT
- LocalFS file storage (S3 abstraction interface; impl deferred to phase 2)

**Phase 2 (deferred):**
- File snapshot tier (incoming customer files, outgoing dossier preservation, immutable versioning)
- S3-compat backend (Cloudflare R2, MinIO)
- Search/browse UI improvements
- Retention policy enforcement (regulatory: 5-10 year retention per TT 39/2018)

## Three deployment shapes per agency

- Data Hub only — agency uses master records management only.
- Data Hub + BCQT — agency does settlement, no CO.
- Data Hub + BCQT + CO — full workflow (default expected).

BCQT solo (without Data Hub) is **not a supported shape**.

## Code seed

Develop Data Hub from CO codebase (`~/workspace/client/barry-CO-main`), not from BCQT-System. CO already handles BCCT + Danh Mục + BOM reasonably well, already on Postgres, advanced BOM versioning. BCQT migrates to consumer mode (less refactor than extracting from BCQT and porting CO).

## Sister repos

- **`~/workspace/client/BCQT-System`** — settlement product. Has mature BCCT/material parsers (~770 tests) + reference projects (Growatt/DKE/Johnson). Read its `.ai/DECISIONS.md` for full context, especially `2026-04-30 PM — Data Hub 3-app architecture`.
- **`~/workspace/client/barry-CO-main`** — origin certificate product. Postgres + BOM versioning. **Code seed for Data Hub MVP.** Audit-only during discovery (don't write code into it from this repo's sessions).

## Reference: full architecture rationale

`~/workspace/client/BCQT-System/.ai/DECISIONS.md` → "2026-04-30 PM — Data Hub 3-app architecture" entry. Definitive source for the decision history, why the shape was picked, what alternatives were rejected.

`~/workspace/client/BCQT-System/docs/design/SYSTEM_SCOPE.md` → product context, three sides (Tinsu AI / Agency / DNCX), engagement types.

`~/workspace/client/BCQT-System/docs/design/IMPLEMENTATION_PHASES.md` → M9 section covers 3-app extraction sub-milestones.

## Next step: M9 discovery sprint

3-5 days, no implementation code. Deliverables:

1. **CO schema audit** — read `~/workspace/client/barry-CO-main/db/migrations/` (5 numbered files, 001..005) + the `*_store.py` files in `app/`; document actual schema for BCCT / Danh Mục / BOM.
2. **Schema diff** vs BCQT current per entity. Alignment plan: which schema is canonical for each.
3. **Storage abstraction design** — `FileBackend` interface, LocalFS day 1, S3-compat phase 2.
4. **SSO design** — auth model, user table, token vs session, cross-app cookie sharing.
5. **Service-to-service auth** — CO → Data Hub write API. Token-based service account, scope per app.
6. **M9 deployment shape** — 1 VPS / Postgres / 3 systemd units / shared file volume / Litestream + pg_dump backup pipeline.

**Output:** feature brief at `.ai/features/2026-04-30-data-hub-mvp.md` with manual test plan + done criteria.

After discovery sprint, implementation phases (~5-7 weeks total): Data Hub MVP build → BCQT migrate to consumer → CO migrate to write-via-API → deployment.

## Conventions (will inherit from BCQT-System once Python project is scaffolded)

- 4 spaces Python, 2 spaces YAML/JSON
- Commit messages in English, no Co-Authored-By trailer
- Every commit references its issue — `Closes #31`, `Refs #33`. `/code-review`'s Spec axis
  resolves the spec from that reference; without it the axis has nothing to check against
- Vietnamese comments only where domain terms have no good English equivalent
- Test-first for risky changes, test-after acceptable for cosmetic
- Sprint-end retrospective ritual (when Python project is scaffolded, copy `make retro` infra)

## Tech stack (TBD — picked after CO audit)

Will likely match CO's existing choices to minimize friction:
- Python (likely 3.12, match BCQT-System)
- FastAPI (assumed; verify in audit)
- Postgres (confirmed — CO uses Postgres)
- ORM TBD: SQLAlchemy / psycopg raw / Pydantic / etc. — pick after audit
- Migration tool TBD: Alembic / raw SQL / etc.

## Build & Run

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8754 --workers 4
# Login admin@data-hub.local / admin123 (role=dev)
#
# The password is `app/main.py`'s DATA_HUB_SEED_PASSWORD default. Nothing
# in app/ loads `.env` (no dotenv import), so .env's DATA_HUB_SEED_PASSWORD
# never reaches the seed — export it in the environment if you want another
# value, and note the admin is seeded only when hub.users is empty, so
# changing it later needs a re-seed, not just an env var.
#
# Why 4 workers: routes are `async def` but do blocking sync DB I/O
# (psycopg `connect()`), so each DB-bound request blocks its worker's
# event loop — workers, not async, are the real concurrency mechanism.
# The original "concurrency for sister-app paginated calls" rationale is
# largely moot now: the BOM batch endpoint
# (POST /v1/hub/products/bom/artifacts:batch) collapsed CO's ~150
# per-product calls to 1. The async+blocking-DB reason is why >1 worker
# still matters in prod; the proper fix would be sync `def` routes
# (Starlette threadpools them) or async psycopg.
# `--workers N` is mutually exclusive with `--reload`, so no auto-reload
# — manual restart after code changes. For dev, `--workers 1 --reload`
# is fine now (and lets you attach a debugger); use more workers only to
# test real concurrency.

uv run pytest -q                                          # ~1670 passed, 16 skipped (2026-07-17)
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q # +real-data smoke (env-gated)
```

The count is dated because it rots — it read "219 passed" until 2026-07-17,
off by ~7x, and two agents wasted a run each believing it. Treat it as an
order of magnitude, not a gate. The gate is "0 failed".

Run the suite **serially** (`-p no:randomly`, one session at a time). It hits
the *shared* dev DB `postgresql:///data_hub` — not an isolated test DB (only
CI overrides `DATA_HUB_DATABASE_URL`). Two consequences bite hard:

- **Concurrent runs invent failures.** Two pytest sessions at once produce
  phantom reds that pass in isolation and vanish on re-run.
- **A migration on one branch reds every other branch, including `main`.** The
  DB is shared across branches and worktrees, so branch B's tests run against
  branch A's schema. This is deterministic, survives a serial re-run, and looks
  exactly like "main is broken". It resolves on merge. A git worktree isolates
  files, **not** the database.

So a red run on one branch proves nothing while another branch holds an
unmerged migration. The only trustworthy gate is the merged tree, run serially.

### Dev port — pinned to **8754**

This is not negotiable. CO's JWT issuer validation expects `http://127.0.0.1:8754` (see `~/workspace/client/barry-CO-main/.ai/STATUS.md` — "CO expected `http://127.0.0.1:8754`, Data Hub issued `iss=http://localhost:8754`" past incident). Same hardcoded in `deploy/systemd/data-hub.service`, `deploy/nginx/data-hub.conf`, `scripts/smoke_real_uploads.py`, `scripts/screenshot.py`, `docs/API_CONTRACT.md`, `README.md`. Sister apps: BCQT runs on 8000.

Do not pick a different port for dev runs. If 8754 is in use, find and stop the existing process — don't start on a different port.

## How We Work

Scale rigor to the change. Inherits from BCQT-System conventions:

- **Risky changes** (schema, auth, API contracts, migrations): `/discover` first → `/tdd` → `/code-review` → commit
- **Standard features**: write tests → implement → `/code-review` → commit
- **Quick fixes**: implement → verify → commit
- **Bug investigation**: `/fix` for systematic root-cause analysis → regression test → fix
- **Session end**: `/handoff` to capture state for next session. **The user must type
  it** — it sets `disable-model-invocation`, so the agent cannot call it. When the user
  doesn't, the agent writes `.ai/sessions/YYYY-MM-DD-<topic>.md` and updates
  `.ai/STATUS.md` by hand instead.

### Principles
- **Progressive rigor:** small change = lightweight; risky change = thorough spec + review.
- **Assumptions mode:** state assumptions from reading code rather than asking many questions. User corrects what's wrong.
- **Verify before claiming done:** no "done" without running tests/lint and confirming the change works. Evidence, not claims.
- **Cross-repo coordination:** changes that affect Data Hub schema (consumed by BCQT/CO) need to update BCQT-System + CO repos accordingly. Document schema changes in `.ai/DECISIONS.md` here AND cross-link from sister repos.

### UI proof & screenshots (two-tier — do not mix)

Any change that touches a UI surface needs visual proof. There are **exactly
two** screenshot locations; never invent a third.

1. **Committed proof** → `.ai/features/<YYYY-MM-DD-slug>/screenshots/*.png`,
   alongside `brief.md` and the `ui_smoke.py` that produced them. This is the
   deliverable. The smoke script lives **in** the feature folder and writes to
   **its own** folder:
   ```python
   OUT = Path(__file__).resolve().parent / "screenshots"
   ```
   Run it with the dev server up on :8754:
   `uv run python .ai/features/<slug>/ui_smoke.py`. If it needs `app` imports,
   bootstrap sys.path to repo root (`sys.path.insert(0, str(Path(__file__).resolve().parents[3]))`).
2. **Scratch / throwaway** → `data/screenshots/` (gitignored). Ad-hoc checks
   during dev only, e.g. the broad walk in `scripts/screenshot.py`. Never
   committed, never the deliverable.

Rules:
- Never write deliverable screenshots into `data/screenshots/`, and never create
  ad-hoc screenshot subfolders anywhere else (no `data/screenshots/<feature>/`,
  no repo-root dumps). One feature = one `.ai/features/<slug>/` — reuse the slug.
- New UI features always use the folder layout; the flat `.ai/features/*.md`
  files are legacy and stay as-is.

## Skills

All available via user-level `~/.claude/skills/`.

Agent-invocable — the agent calls these itself:

- `/tdd` — test-driven development
- `/code-review` — the closing review; two axes, parallel sub-agents (see below)
- `/fix` — systematic debugging
- `/discover` — explore before building
- `/scaffold` — scaffold new code structure
- `/ai-init` — already used to set up this project's AI context
- `/code-review`, `/codebase-design`, `/domain-modeling`, `/grilling`, `/prototype`,
  `/research`, `/diagnosing-bugs`, `/qa`, `/request-refactor-plan`,
  `/resolving-merge-conflicts` — from the Matt Pocock skill pack

User-typed only — these set `disable-model-invocation: true` in their `SKILL.md`, so the
agent cannot call them. Type them at the **start** of a message, or the harness treats
them as plain text:

- `/handoff` — session summary + STATUS.md update
- `/ask-matt` — router: which skill or flow fits this situation
- `/implement`, `/to-spec`, `/to-tickets`, `/triage`, `/wayfinder`,
  `/grill-me`, `/grill-with-docs`, `/improve-codebase-architecture`,
  `/teach`, `/ubiquitous-language`, `/writing-great-skills`

### Agent skills — repo configuration

**Read `docs/agents/flow.md` first** — the whole flow, the on-ramps, and how this repo
deviates from it. Adopted 2026-07-10. One path, no parallel stores.

- **Issue tracker** — GitHub Issues on `TinsuAI/data-hub`, via `gh`. PRs are not a request
  surface. See `docs/agents/issue-tracker.md`.
- **Triage labels** — the five canonical labels, unrenamed. See `docs/agents/triage-labels.md`.
- **Domain docs** — `.ai/GLOSSARY.md` plays the role of `CONTEXT.md`; ADRs live in
  `docs/adr/`. See `docs/agents/domain.md`.

`.ai/BACKLOG.md` is frozen as a historical record: its open items moved to Issues, its
shipped and deferred entries stay. Do not add work items to it. `.ai/DECISIONS.md` is
likewise historical; new decisions become ADRs.

### Review — `/code-review` is the default (changed 2026-07-10)

`/rev` is **retired**. It stays on disk but nothing in this repo's workflow calls it.
`/code-review` is what `/implement` closes with, so using it keeps one flow, not two.

**Two axes, two parallel sub-agents, contexts isolated** so neither masks the other:

- **Standards** — documented repo standards, plus a fixed baseline of 12 Fowler code
  smells. A documented repo standard always overrides the baseline. Smells are labelled
  judgement calls, never hard violations.
- **Spec** — requirements the spec asked for that are missing, behaviour nobody asked for
  (scope creep), and requirements implemented wrongly.

Findings are never merged or reranked across the two axes. That separation is the point.

**Know what it does not do.** Neither axis hunts bugs, security holes, missing error
handling at I/O boundaries, or breaking public-interface changes. `/rev` used to. For a
change that touches auth, migrations, or the `/v1/hub` surface, run the harness's
`/security-review` as a separate pass; `/code-review` will not catch those.

**It needs two inputs.** A fixed point (`main`, a SHA, a tag) for `git diff <point>...HEAD`,
and a spec. The Spec axis finds the spec from issue references in the commit messages, via
`docs/agents/issue-tracker.md`. **So commit messages must reference their issue** —
`Closes #31`, `Refs #33`. Without that reference the Spec axis has nothing to compare
against and skips.

`/setup-matt-pocock-skills` has effectively been run by hand. Do not run it again; it would
add a duplicate `## Agent skills` block.

No project-local skills needed currently. If the project develops Data-Hub-specific workflows that warrant custom skills, add via `ai-skill add` to `.claude/skills/`.

## Context Files

- `.ai/STATUS.md` — current progress and next steps (pre-MVP scaffold; awaiting M9 discovery)
- `.ai/DECISIONS.md` — local decisions (canonical architecture lives in BCQT-System DECISIONS.md for now)
- `.ai/GLOSSARY.md` — domain-specific terms (customs compliance vocabulary)
- `.ai/sessions/` — dated session summaries and primary handoff artifacts
- `.ai/features/<YYYY-MM-DD-slug>/` — per-feature folder: `brief.md` +
  committed `screenshots/*.png` + optional `ui_smoke.py`. Canonical home for
  UI proof — see **"UI proof & screenshots"** under How We Work for the
  two-tier rule (committed here vs gitignored `data/screenshots/` scratch).
  Flat `.ai/features/*.md` files are legacy and stay as-is.
- `docs/release-engineering.md` — Data Hub instance of the
  TinsuAI release-engineering policy. Versioning, branching,
  deployment shapes, seed taxonomy, backup/restore — all mapped
  onto this repo's concrete files, env vars, hosts. Read before
  cutting a release, changing schema, or standing up a new
  environment.

## Standards

This repo follows TinsuAI cross-product standards.

- Canonical source: `TinsuAI/standards` on GitHub (private repo).
- Pinned version: see `.standards-version` at repo root
  (currently `v2026.05.05`).
- Per-product mapping: `docs/release-engineering.md`.
- Policy files (read at the pinned tag):
  - `policies/release-engineering.md`
  - `policies/security.md` (stub)
  - `policies/code-style.md` (stub)
  - `policies/ci-cd.md` (stub)
  - `policies/ai-collaboration.md` (stub)

How AI agents resolve the policy (the standards repo is private,
so direct WebFetch returns 404):

1. **Local checkout**: most maintainer machines have it at
   `~/workspace/client/tinsu-standards`. Read at the pinned
   tag:
   ```
   git -C ~/workspace/client/tinsu-standards show \
       $(cat .standards-version):policies/release-engineering.md
   ```
2. **Authenticated `gh`** as fallback:
   ```
   gh api repos/TinsuAI/standards/contents/policies/release-engineering.md \
       --ref $(cat .standards-version) --jq .content | base64 -d
   ```
3. Otherwise ask the user.

When the standards repo changes, update `.standards-version` and
reconcile `docs/release-engineering.md`. When this repo's reality
diverges from policy, fix the divergence OR open an RFC against
`tinsu-standards` to amend the policy.
