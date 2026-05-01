# Project Status

**Date:** 2026-05-01 (end of day — post-autopilot iteration)

## Current State

**Working MVP web app + read API.** Running locally at `http://127.0.0.1:8754`.
Login: `admin@data-hub.local / admin123`.

What works:
- Client management with workspace pattern (URLs nested under `/clients/{client_id}/{tab}`).
- 7 entity tabs per client: Overview, Catalog, Code Mappings (BQD), BCCT, BOM, Proposals, Uploads, Config.
- Excel upload + parsing for: Materials (5-category enum), BQD (N-to-N), BCCT (Growatt regex internal_code parser), BOM (3 profiles: manual_flat / growatt_multi_workbook / johnson_sap_exploded).
- Code resolver: ports Growatt's BCCT-aggregate disambiguation; runs after BQD/BCCT upload.
- BOM proposal queue: auto-only mode, 5-condition gate, idempotent.
- Public read API: 11 endpoints under `/v1/hub/*`, bearer-token auth.
- BCCT raw columns captured into `payload` jsonb (full Vietnamese headers preserved).
- Dual-source material detection: query-time EXISTS subqueries flag materials present in both BCCT imports + BOM products.
- i18n bilingual: Vietnamese default + English toggle (cookie). ~150 translation keys.
- Auto-seed on empty DB: creates Growatt VN (10 catalog + 8 BQD pairs incl. 1:n + 10 BCCT + 5 BOM versions + 2 proposals) and Johnson VN (4 catalog identity-mode + 3 BCCT + 1 BOM).
- 28 pytest tests passing.
- 27 Playwright UI screenshots in `data/screenshots/` covering all flows in light + dark + EN.

## Recent Changes

**Today (2026-05-01) is one session — see two `.ai/sessions/` files for full breakdown:**

- `2026-05-01-autopilot-mvp-scaffold.md` — initial autopilot build of foundation, schema, auth, entity routers, JSON API, audit views.
- `2026-05-01-client-restructure-i18n-redesign.md` — post-autopilot UX iteration: DNCX→Clients rename, workspace mental model, breadcrumb, dual-source detection, BCCT payload capture, button restyle, i18n overhaul, settings page redesign.

12 commits total since project scaffold (`f1eaae5`).

## Next Steps

1. **Validate against real Growatt data** at `~/workspace/client/bcqt-growatt/data/` — synthetic seed has only 10 BCCT rows; real files have thousands. Test parsers + resolver at scale.
2. **Audit other reference clients** (DKE, Dothanh, Johnson real data) for parser quirks the synthetic seed doesn't surface.
3. **Background job for resolver** — currently runs synchronously inside upload handlers; will block on big uploads. Move to a queue (RQ / arq / celery) when first slow upload appears.
4. **SSO design pass** (M9 deliverable #4) — currently MVP uses single-deployment session-cookie auth + seed admin. Need cross-app SSO design for federation with BCQT and CO.
5. **Service-discovery for auto-rule case_id validation** — currently DROPPED from MVP because CO has no HTTP API. Reinstate when CO grows one.
6. **Manual + hybrid BOM review modes** — schema is shaped to accept these; phase 2 work involves notification system, latency SLO, review queue endpoints.
7. **Production deployment** (M9 deliverable #6) — systemd, pg_dump backup pipeline, Litestream for per-project SQLite (BCQT-side), nginx reverse proxy.
8. **JWT scope auth on read API** — currently accepts any non-empty bearer token; phase 2 adds proper JWT scope validation.

## Blockers

None for MVP validation. Production-ship gates: SSO design + deployment shape.

## Notes for Next AI Session

- **Server is currently running** in background (uvicorn with `--reload`) — pkill if you want a fresh start.
- **Auto-seed runs on empty DB** automatically (lifespan hook). Set `DATA_HUB_AUTO_SEED_DEMO=0` to disable. Reset state with `psql -d data_hub -c "truncate hub.clients cascade"`.
- **Vietnamese is the default UI language**, English is the alternate. `t()` Jinja callable dispatches via `data_hub_lang` cookie. Translation dict in `app/i18n.py` (~150 keys, structured by domain prefix: nav/auth/common/clients/workspace/tabs/catalog/bqd/bcct/bom/proposals/uploads/status).
- **Mental model: Client first, then workspace.** All entity URLs nested under `/clients/{client_id}/{tab}`. There's no global "all materials across clients" view — that was rejected as wrong UX.
- **Code seed is `barry-CO-main` (capital CO)** at `~/workspace/client/barry-CO-main`. The lowercase `barry-co-main` doesn't exist on disk — fixed in earlier session but worth re-noting if you `cd` based on memory.
- **Dual-source materials** are detected at query time (EXISTS subqueries in catalog list query). NOT stored. Cost is negligible at current scale (indexes cover both subqueries). Phase 2 may materialize.
- **BCCT payload jsonb captures every column** from source workbook by original Vietnamese header name. Typed columns are query/index layer; payload is raw archive. Real HQ Excels with 25-30 columns will preserve all of them.
- **CSS is mostly inherited verbatim from CO** (`barry-CO-main/app/static/css/app.css`, ~1300 lines). Data Hub appended ~150 lines for breadcrumb, settings page, button restyle, dual badge, dark theme tweaks.
- **Sister-repo cross-link decisions**: anchor architecture in `~/workspace/client/BCQT-System/.ai/DECISIONS.md` "2026-04-30 PM — Data Hub 3-app architecture" with 2026-05-01 BCCT-amendment block at top.

## Reference

- Sister repos:
  - `~/workspace/client/BCQT-System` — settlement product, future consumer of Data Hub
  - `~/workspace/client/barry-CO-main` — origin certificate product, code seed
  - `~/workspace/client/bcqt-growatt` — Growatt reference data + N-N mapping algorithm port
- Local design docs:
  - `.ai/DECISIONS.md` — local architecture decisions log
  - `.ai/features/2026-04-30-data-hub-mvp.md` — original discovery brief (3 critique rounds + amendments)
  - `.ai/features/2026-05-01-data-hub-read-api.md` — read-API contract design (v2)
  - `.ai/features/epic-2026-05-01-data-hub-mvp.md` — MVP epic plan + waves
  - `.ai/sessions/` — dated session summaries (this and one autopilot)
- Demo + dev:
  - `scripts/seed_demo.py` — HTTP-based demo seeder (alternative to auto-seed)
  - `scripts/screenshot.py` — Playwright UI capture
- Memory: `~/.claude/projects/-home-vp-workspace-client-data-hub/memory/`
  - `project_architecture_lock.md`, `project_bom_multisource.md`, `reference_co_codebase.md`
