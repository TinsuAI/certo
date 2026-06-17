# Architecture Decisions

<!-- Format:
## [Date] Decision Title
**Context:** Why this decision was needed
**Decision:** What was decided
**Alternatives:** What else was considered
**Consequences:** What this means going forward
-->

## [2026-04-15] Defer Application Stack Until Discovery Completes
**Context:** The user asked for project bootstrap in the sense of metadata and data exploration, not immediate application scaffolding.
**Decision:** Do not commit to a web application stack yet; keep the repo focused on archive extraction, project context, and data discovery.
**Alternatives:** Scaffold a frontend or backend before understanding the data and workflow.
**Consequences:** The next architecture decision should be made against the actual CO process and dataset, not against a guessed UI stack.

## [2026-04-15] Discovery Is File-System Backed First
**Context:** The only reliable source material today is the agency archive, including spreadsheets, PDFs, ZIPs, and RARs.
**Decision:** Treat `data/extracted/CO` as the discovery source of truth for the bootstrap phase instead of inventing seed data or introducing a database immediately.
**Alternatives:** Start with mock data, or design the full relational model before reading the real files.
**Consequences:** Planning stays anchored to the actual case structure, but the next phase must normalize spreadsheet and document metadata into app-owned entities.

## [2026-04-15] Use JS-Based RAR Extraction
**Context:** The environment does not include a native `unrar` binary, but the supplied archive set contains multiple `.rar` bundles that are part of active and completed cases.
**Decision:** Add `node-unrar-js` and provide a local extraction script.
**Alternatives:** Leave RAR files opaque, depend on manual extraction outside the repo, or install platform-specific native tooling.
**Consequences:** Discovery remains reproducible within the project, and future ingestion flows can reuse the same JS-based archive support.

## [2026-04-27] Use FastAPI/Jinja For First CO Demo Shell
**Context:** The user asked for a working demo webapp for preparing a simple C/O case, with BCQT-System as the reference implementation style.
**Decision:** Add a small FastAPI/Jinja demo app in this repo for the first C/O preparation surface. This is a demo shell decision, not a final production architecture decision.
**Alternatives:** Continue with Node-only scripts, or scaffold a larger frontend/backend stack before validating the C/O workflow.
**Consequences:** The demo can reuse the same operational UI pattern as BCQT-System while keeping the final database/auth/deploy decisions open.

## [2026-06-17] Consolidate worktree split → single standalone repo
**Context:** Two confusing CO folders under `/home/vp/workspace/client/`: `barry-CO` (the main git working tree that held the canonical `.git`, but was stuck on a stale April branch `case/growatt-rvc-20260421` with uncommitted experiment scripts) and `barry-CO-main` (a linked worktree carrying all active `main` work). The real `.git` lived in the stale folder — backwards and confusing.
**Decision:** Re-init `barry-CO-main` as a standalone repo from `origin` (TinsuAI/co — `main` was fully pushed), preserving working tree + `.env` + the `data` symlink in place; repoint upstream to `origin/main`; then delete `barry-CO`.
**Alternatives:** Fresh clone into a new folder (loses local-only `.env`/`data`/uncommitted `.ai`); manual git-pointer surgery (riskier); leave the split.
**Consequences / RECOVERY POINTERS:**
- `barry-CO`'s uncommitted experiment scripts → saved on origin branch **`case/growatt-rvc-20260421`** @ `26b6476`. Recover: `git fetch origin case/growatt-rvc-20260421 && git checkout case/growatt-rvc-20260421`.
- Deleted `barry-CO` was the old predecessor checkout; all committed content is the shared repo history already on origin (same repo) — nothing unique lost beyond the branch above.
- Earlier this session: **CO cases + claims fully purged (dev + prod, all clients)**. Restorable backups at `barry-CO-bom-data/local/backups/full-purge-20260615-032608/` — dev (`db_cases_claims.sql`, `claim_events.csv`, `db_supporting_files.sql`, `cases-json/`, `uploads-growatt-vn/`) + `prod/` (`db_cases_claims.sql`, `claim_events.csv`, `co-cases-files.tar.gz`). Stock (`co_stock_rows`) was NOT purged. Restore via `psql` (dev local socket; prod `docker exec -i co-db-1 psql -U co -d barry_co`).
- `barry-CO-main` is now standalone (own `.git`, single remote `origin`); no worktree split remains.
