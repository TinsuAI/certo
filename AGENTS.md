# Project: Data Hub (provisional)

## Overview

**Vendor:** Tinsu AI (bespoke software solutions company).
**Product:** Data Hub — agency master records management. One of three Tinsu AI products serving customs compliance agencies.
**Status:** Pre-MVP scaffold (2026-04-30). No code yet. Awaiting M9 discovery sprint.

**Naming:** "Data Hub" is provisional working name. Marketing/branding name not yet locked. Repo path + Postgres schema names may rename later.

## Three Tinsu AI products (locked 2026-04-30 PM)

1. **Data Hub** *(this repo)* — master records management. Owns shared HQ-data tier (BCCT + Danh Mục NVL/SP/BTP + BOM in MVP; file snapshots phase 2).
2. **BCQT-System** (`~/workspace/client/BCQT-System`) — annual settlement reports (Mẫu 15 / 15a / 16). Read-only consumer of Data Hub.
3. **CO-System** (`~/workspace/client/barry-co-main`) — origin certificates per-shipment. Read-only consumer of Data Hub for HQ-data; writes per-shipment BCCT to Data Hub via API.

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

Develop Data Hub from CO codebase (`~/workspace/client/barry-co-main`), not from BCQT-System. CO already handles BCCT + Danh Mục + BOM reasonably well, already on Postgres, advanced BOM versioning. BCQT migrates to consumer mode (less refactor than extracting from BCQT and porting CO).

## Sister repos

- **`~/workspace/client/BCQT-System`** — settlement product. Has mature BCCT/material parsers (~770 tests) + reference projects (Growatt/DKE/Johnson). Read its `.ai/DECISIONS.md` for full context, especially `2026-04-30 PM — Data Hub 3-app architecture`.
- **`~/workspace/client/barry-co-main`** — origin certificate product. Postgres + BOM versioning. **Code seed for Data Hub MVP.** Audit-only during discovery (don't write code into it from this repo's sessions).

## Reference: full architecture rationale

`~/workspace/client/BCQT-System/.ai/DECISIONS.md` → "2026-04-30 PM — Data Hub 3-app architecture" entry. Definitive source for the decision history, why the shape was picked, what alternatives were rejected.

`~/workspace/client/BCQT-System/docs/design/SYSTEM_SCOPE.md` → product context, three sides (Tinsu AI / Agency / DNCX), engagement types.

`~/workspace/client/BCQT-System/docs/design/IMPLEMENTATION_PHASES.md` → M9 section covers 3-app extraction sub-milestones.

## Next step: M9 discovery sprint

3-5 days, no implementation code. Deliverables:

1. **CO schema audit** — read `~/workspace/client/barry-co-main` code (no migration files exist yet); document actual schema for BCCT / Danh Mục / BOM.
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
