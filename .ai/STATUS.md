# Project Status

**Date:** 2026-05-02 (RBAC + per-client ACL landed; settlement resolver ripped out of hub)

## Current State

**Working MVP web app + read API + 4-role auth.** Running locally at `http://127.0.0.1:8754`.
Login: `admin@data-hub.local / admin123` (role=`dev`).

What works:
- Client management with workspace pattern (URLs nested under `/clients/{client_id}/{tab}`).
- 7+1 entity tabs per client: Overview, Catalog, Code Mappings (BQD), BCCT, BOM, Proposals, Uploads, Staff (admin/manager-of-this-client only), Config.
- Excel upload + parsing for: Materials (5-category enum), BQD (N-to-N), BCCT (Growatt regex internal_code parser), BOM (3 profiles: manual_flat / growatt_multi_workbook / johnson_sap_exploded).
- Code parser: extracts `internal_code` from BCCT `goods_name` at upload time (Growatt regex). Settlement-flavored canonical-code resolver was REMOVED from hub on 2026-05-02 — see DECISIONS entry. Resolver script lives at `scripts/settlement_resolver.py` (CLI-only, hub-runtime-isolated, destined for BCQT migration).
- BOM proposal queue: auto-only mode, 5-condition gate, idempotent.
- Public read API: 11 endpoints under `/v1/hub/*`, bearer-token auth.
- BCCT raw columns captured into `payload` jsonb (full Vietnamese headers preserved).
- Dual-source material detection: query-time EXISTS subqueries flag materials present in both BCCT imports + BOM products.
- i18n bilingual: Vietnamese default + English toggle (cookie). ~200 translation keys.
- Auto-seed on empty DB: creates Growatt VN (10 catalog + 8 BQD pairs incl. 1:n + 10 BCCT + 5 BOM versions + 2 proposals) and Johnson VN (4 catalog identity-mode + 3 BCCT + 1 BOM).
- **4-role RBAC + per-client ACL** (2026-05-02):
  - Roles: `dev` (single, vendor) / `admin` / `manager` (scoped to client group) / `staff` (per-client read|edit).
  - Migration 008: role CHECK constraint, partial unique index for single-dev, `hub.user_managed_clients`, `hub.user_client_access`.
  - Admin UI at `/admin/users` (list/create/role/lock) + `/admin/users/{id}/clients` (manager group).
  - Per-client `/clients/{id}/staff` tab for manager-of-client/admin/dev.
  - Permission gates wired into all per-client routes (catalog/bqd/bcct/bom/uploads/proposals/config).
- 40 pytest tests passing (45 - 5 dropped resolver tests).
- 27 Playwright UI screenshots in `data/screenshots/` covering all flows in light + dark + EN.

## Recent Changes

**2026-05-02 — Settlement resolver ripped out of hub.** After critic review, removed BCQT-flavored canonical-code resolver from hub (was a lossy port of bcqt-growatt algorithm — wrong for TP today). Migration `009_rip_resolver.sql` drops `hub.code_mapping_resolutions` + `bcct_rows.resolved_customs_code`. Algorithm moved to `scripts/settlement_resolver.py` (CLI). DECISIONS entry "2026-05-02 Settlement code resolver moved out of hub". Brief: `.ai/features/2026-05-02-rip-resolver-from-hub.md`.

**2026-05-02 — RBAC + per-client ACL.** Feature brief: `.ai/features/2026-05-02-auth-rbac-acl.md`. Session: `.ai/sessions/2026-05-02-rbac-acl.md`. Pre-SSO phase: cross-app token issuer deferred until BCQT/CO consumers exist.

**2026-05-01 (full day):**
- `2026-05-01-autopilot-mvp-scaffold.md` — initial autopilot build of foundation, schema, auth, entity routers, JSON API, audit views.
- `2026-05-01-client-restructure-i18n-redesign.md` — post-autopilot UX iteration: DNCX→Clients rename, workspace mental model, breadcrumb, dual-source detection, BCCT payload capture, button restyle, i18n overhaul, settings page redesign.

## Next Steps

1. **Validate against real Growatt data** at `~/workspace/client/bcqt-growatt/data/` — synthetic seed has only 10 BCCT rows; real files have thousands. Test parsers + resolver at scale.
2. **Audit other reference clients** (DKE, Dothanh, Johnson real data) for parser quirks the synthetic seed doesn't surface.
3. **Background job for resolver** — currently runs synchronously inside upload handlers; will block on big uploads. Move to a queue (RQ / arq / celery) when first slow upload appears.
4. **Cross-app SSO Phase 2** (M9 deliverable #4) — local RBAC + ACL is in place. Phase 2 = JWT issuer / JWKS / cookie-domain federation when BCQT and CO consumers come online. Defer until BCQT/CO migration audits land.
5. **Service-discovery for auto-rule case_id validation** — currently DROPPED from MVP because CO has no HTTP API. Reinstate when CO grows one.
6. **Manual + hybrid BOM review modes** — schema is shaped to accept these; phase 2 work involves notification system, latency SLO, review queue endpoints.
7. **Production deployment** (M9 deliverable #6) — systemd, pg_dump backup pipeline, Litestream for per-project SQLite (BCQT-side), nginx reverse proxy.
8. **JWT scope auth on read API** — currently accepts any non-empty bearer token; phase 2 adds proper JWT scope validation.
9. **Audit log UI for permission changes** — `granted_by`/`granted_at` columns are populated; an admin-side history view is deferred.
10. **Password reset / invite email / 2FA** — current admin creates user with chosen password directly; phase 2 should add reset flow, invite emails, optional 2FA.

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
