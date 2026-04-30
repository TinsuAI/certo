# Project Status

**Date:** 2026-05-01 PM (autopilot session)

## Currently Working On

**MVP scaffold shipped end-to-end.** A full FastAPI + Postgres + Jinja2 web app with:
- 7 DB tables across 6 migrations (`hub` schema)
- Argon2 session-based auth, seed admin
- 5 entity routers + 11-endpoint JSON read API
- Excel parsers (Materials, BQD, BCCT, BOM in 3 profiles) with Growatt regex
- Code resolution worker (Growatt-style 1:n disambiguation via BCCT aggregates)
- BOM proposal queue with auto-rule (5-condition gate, idempotent)
- 28 passing pytest tests
- Playwright UI screenshots (16 light + 4 dark)

Run: `uv run uvicorn app.main:app --port 8754`. Login: `admin@data-hub.local / admin123`.

## Recent Changes

- 2026-05-01 (autopilot): scaffold → SSO → DNCX → Materials/Mappings → BCCT (Growatt regex) → BOM (8-table model + proposal queue) → resolver → JSON API → audit views (proposals, uploads). 6 commits, 30+ source files, ~3500 LOC.
- 2026-05-01 evening: locked BOM-write-via-proposal pattern (auto-only MVP), point-of-use binding, two-axis (actor, intent) provenance, immutable per-DNCX `code_resolution_mode`, deferred SSO design + manual review mode + S3 storage to phase 2.
- 2026-04-30: design week — CO schema audit, brief drafted + 3 critique rounds, BCCT amendment (single-writer for MVP), tracking-code shape verified against Growatt.

## Next Steps

1. **Real SSO design pass.** Currently MVP uses a single-deployment auth center with seed admin. Need to design: cross-app session sharing (data-hub ↔ BCQT ↔ CO), token model, role/scope matrix.
2. **Run `code_resolution` worker as background job** (currently runs synchronously after BCCT/BQD upload — fine for now but will block on big uploads). Consider Celery / RQ / async task queue when uploads grow.
3. **Test against real Growatt data** (~/workspace/client/bcqt-growatt/data/). Current synthetic seed has 5 BCCT rows; real Growatt files have thousands. Validate parser performance + resolver correctness at scale.
4. **Additional auto-rule criteria for BOM proposals.** The 5-condition gate is speculative; tune against real CO modification flows when CO integration starts.
5. **Production deployment shape** (M9 deliverable #6): 1 VPS / systemd / pg_dump backup / nginx reverse proxy. Not done — currently dev-only.
6. **Real Growatt BOM upload validation** — only `manual_flat` profile tested with synthetic data. Validate `growatt_multi_workbook` against real data.
7. **CO write-API integration.** Currently the proposal endpoint accepts any bearer token; phase 2 adds JWT scope checks (`hub:propose:bom`).

## Blockers

None for MVP scaffold. Production deployment + cross-app SSO are the gates for real shipping.

## Notes for Next AI Session

- All design rationale lives in `.ai/DECISIONS.md` (this repo) and `~/workspace/client/BCQT-System/.ai/DECISIONS.md` (canonical 3-app architecture).
- Read-API contract is at `.ai/features/2026-05-01-data-hub-read-api.md` (v2 — covers axis-split, point-of-use binding, idempotency canonicalization, tracking-code-mode).
- Epic plan at `.ai/features/epic-2026-05-01-data-hub-mvp.md` — sequence and done criteria (most done).
- Memory under `~/.claude/projects/-home-vp-workspace-client-data-hub/memory/`:
  - `project_architecture_lock.md` — 3-app architecture
  - `project_bom_multisource.md` — proposal pattern + provenance axes
  - `reference_co_codebase.md` — `~/workspace/client/barry-CO-main` (capital CO)
- Sister-repo `BCQT-System/.ai/DECISIONS.md` line 443 has a 2026-05-01 amendment block at top of the canonical entry.
- Tech stack inherited from CO: FastAPI + Jinja2 + psycopg + raw SQL migrations + uv + argon2-cffi. Tests use pytest + httpx + playwright.

## Reference

- Sister repos:
  - `~/workspace/client/BCQT-System` — settlement product, will become consumer
  - `~/workspace/client/barry-CO-main` — origin certificates, code seed
  - `~/workspace/client/bcqt-growatt` — Growatt reference data + N-N mapping algorithm port
- Demo data seed: `scripts/seed_demo.py` (uploads synthetic Growatt-shape Excel via HTTP)
- UI screenshots: `data/screenshots/`
