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
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload
# Login admin@data-hub.local / admin123 (role=dev)

uv run pytest -q                                          # 219 passed, 15 skipped
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q # +real-data smoke (env-gated)
```

### Dev port — pinned to **8754**

This is not negotiable. CO's JWT issuer validation expects `http://127.0.0.1:8754` (see `~/workspace/client/barry-CO-main/.ai/STATUS.md` — "CO expected `http://127.0.0.1:8754`, Data Hub issued `iss=http://localhost:8754`" past incident). Same hardcoded in `deploy/systemd/data-hub.service`, `deploy/nginx/data-hub.conf`, `scripts/smoke_real_uploads.py`, `scripts/screenshot.py`, `docs/API_CONTRACT.md`, `README.md`. Sister apps: BCQT runs on 8000.

Do not pick a different port for dev runs. If 8754 is in use, find and stop the existing process — don't start on a different port.

## How We Work

Scale rigor to the change. Inherits from BCQT-System conventions:

- **Risky changes** (schema, auth, API contracts, migrations): `/discover` first → `/tdd` → `/rev` → commit
- **Standard features**: write tests → implement → `/rev` → commit
- **Quick fixes**: implement → verify → commit
- **Bug investigation**: `/fix` for systematic root-cause analysis → regression test → fix
- **Session end**: `/handoff` to capture state for next session

### Principles
- **Progressive rigor:** small change = lightweight; risky change = thorough spec + review.
- **Assumptions mode:** state assumptions from reading code rather than asking many questions. User corrects what's wrong.
- **Verify before claiming done:** no "done" without running tests/lint and confirming the change works. Evidence, not claims.
- **Cross-repo coordination:** changes that affect Data Hub schema (consumed by BCQT/CO) need to update BCQT-System + CO repos accordingly. Document schema changes in `.ai/DECISIONS.md` here AND cross-link from sister repos.

## Skills

All available via user-level `~/.claude/skills/`:

- `/tdd` — test-driven development
- `/rev` — two-stage code review
- `/fix` — systematic debugging
- `/discover` — explore before building (use to scope M9 discovery sprint deliverables)
- `/handoff` — session summary + STATUS.md update
- `/scaffold` — scaffold new code structure (will use when picking tech stack post-audit)
- `/ai-init` — already used to set up this project's AI context

No project-local skills needed currently. If the project develops Data-Hub-specific workflows that warrant custom skills, add via `ai-skill add` to `.claude/skills/`.

## Context Files

- `.ai/STATUS.md` — current progress and next steps (pre-MVP scaffold; awaiting M9 discovery)
- `.ai/DECISIONS.md` — local decisions (canonical architecture lives in BCQT-System DECISIONS.md for now)
- `.ai/GLOSSARY.md` — domain-specific terms (customs compliance vocabulary)
- `.ai/sessions/` — dated session summaries and primary handoff artifacts
