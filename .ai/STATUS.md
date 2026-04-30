# Project Status

**Date:** 2026-04-30 PM (initial scaffold)

## Currently Working On

Pre-MVP scaffold. No code yet. Awaiting M9 discovery sprint.

## Recent Changes

- 2026-04-30: Initial scaffold (`mkdir`, `git init`, `.gitignore`, `README.md`, `AGENTS.md`).
- 2026-04-30: `ai-init --type app` to set up `.ai/` structure + global skills + symlinks (CLAUDE.md, GEMINI.md → AGENTS.md).

## Next Steps

**M9 discovery sprint** (3-5 days, no code):

1. Audit CO codebase (`~/workspace/client/barry-co-main`) — schema for BCCT / Danh Mục / BOM. Document actual structure since CO has no migration files.
2. Schema diff Data Hub canonical (from CO seed) vs BCQT current. Alignment plan per entity.
3. `FileBackend` interface design — LocalFS day 1, S3-compat phase 2.
4. SSO design — auth model, user table, token vs session, cross-app cookie sharing.
5. Service-to-service auth — CO → Data Hub write API. Token-based service account.
6. M9 deployment shape — 1 VPS / Postgres / 3 systemd unit / shared file volume / Litestream + pg_dump backup pipeline.

**Output of discovery sprint:** feature brief at `.ai/features/2026-04-30-data-hub-mvp.md` (when `.ai/features/` is added) with manual test plan + done criteria.

After discovery: implementation phases (~5-7 weeks): Data Hub MVP build → BCQT consumer migration → CO write-via-API migration → deployment.

## Blockers

None at scaffold stage. Discovery sprint requires read-access to `~/workspace/client/barry-co-main`.

## Notes for Next AI Session

- **Naming is provisional.** "Data Hub" may rebrand. Treat as reference symbol, not brand commitment. Repo path + Postgres schema names may rename later.
- **Code seed is CO, not BCQT.** CO already on Postgres + has BOM versioning advanced + handles BCCT/Danh Mục/BOM reasonably well. BCQT migrates to consumer mode.
- **Cross-repo decision context** lives in `~/workspace/client/BCQT-System/.ai/DECISIONS.md` → "2026-04-30 PM — Data Hub 3-app architecture". Read that BEFORE starting any architectural work.
- **Don't write code into `barry-co-main` from this repo's session.** CO development happens in its own session. Audit-only here.
- **Tech stack TBD.** Pick after CO audit to match (minimize friction). Likely Python 3.12 + FastAPI + Postgres + SQLAlchemy/psycopg.
- **MVP scope is structured tier only** (BCCT + Danh Mục + BOM parsed → Postgres). File snapshot tier deferred to phase 2.

## Reference

- Sister repos:
  - `~/workspace/client/BCQT-System` — settlement product (mature parsers, ~770 tests)
  - `~/workspace/client/barry-co-main` — origin certificates product (Postgres, MVP, code seed for Data Hub)
- Canonical architecture decision: `~/workspace/client/BCQT-System/.ai/DECISIONS.md` "2026-04-30 PM — Data Hub 3-app architecture"
- Product context: `~/workspace/client/BCQT-System/docs/design/SYSTEM_SCOPE.md` (3 Tinsu products, 3 deployment shapes)
- Milestones: `~/workspace/client/BCQT-System/docs/design/IMPLEMENTATION_PHASES.md` M9 section
