# Project Status

**Date:** 2026-05-03 EOD (HTTP-route real-data run; 4 more fixes landed)

## Current State

**Working MVP web app + read API + 4-role auth.** Server NOT running (stopped pre-commit).
Start with: `uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload`.
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
- i18n bilingual: Vietnamese default + English toggle (cookie). ~190 translation keys.
- Auto-seed on empty DB: creates Growatt VN (10 catalog + 8 BQD pairs incl. 1:n + 10 BCCT + 5 BOM versions + 2 proposals) and Johnson VN (4 catalog identity-mode + 3 BCCT + 1 BOM).
- **4-role RBAC + per-client ACL** (2026-05-02):
  - Roles: `dev` (single, vendor) / `admin` / `manager` (scoped to client group) / `staff` (per-client read|edit).
  - Migration 008: role CHECK constraint, partial unique index for single-dev, `hub.user_managed_clients`, `hub.user_client_access`.
  - Admin UI at `/admin/users` (list/create/role/lock) + `/admin/users/{id}/clients` (manager group).
  - Per-client `/clients/{id}/staff` tab for manager-of-client/admin/dev.
  - Permission gates wired into all per-client routes (catalog/bqd/bcct/bom/uploads/proposals/config).
- 68 pytest tests passing + 7 skipped (real-data, env-gated). 0 xfail (all parser bugs fixed).
- With real-data dir set: +6 more passing (real `.xls` BCCT for Growatt/DKE/Dothanh + Growatt 51MB settlement workbook).
- 27 Playwright UI screenshots in `data/screenshots/` covering all flows in light + dark + EN.
- Fixture corpus at `tests/fixtures/` (18 manual `.xlsx` + 9 synthetic edge cases incl. 2 legacy `.xls`). Driven by `tests/test_fixture_corpus.py`. Real `.xls`/`.xlsm` via `DATA_HUB_REAL_DATA_DIR` env var (`tests/test_real_data_external.py`).

## Recent Changes

**2026-05-03 (EOD revised) — HTTP-route real-data run + correction round.** Drove all 5 real `.xls` BCCT files through `/clients/{id}/bcct/upload` (Growatt NK 3045 + XK 137, Dothanh E31 132 + E62 317, DKE 2025 1488 — total 5119 rows). Idempotent re-upload verified. DKE Danh Mục NPL+SP through `/clients/{id}/catalog/upload` — 45 materials. Dual-source: 44/45 DKE in BCCT, 3/4 Johnson.

Route-layer fixes landed: (1) declaration types extended H11-H13/H21-H23/C11-C12 (23 rows had `direction=NULL`); (2) materials parser fallback alias `Mã` for single-column Danh Mục files (DKE shape); (3) materials `status` normalizer (Vietnamese "Đã duyệt" / "Đang dùng" / "Chờ duyệt" → DB enum).

**Correction (after user feedback):** initial fix that fell back `internal_code = customs_code` when goods_name parser missed was *wrong* — internal_code (agency's ERP code) and customs_code (HQ-assigned) are distinct concepts. BCCT files don't carry internal_code; hub derives it via per-client parser. NULL is the correct state when the parser can't extract; staff/BQD maps it later. Reverted: route now does `internal_code = customs_code` ONLY when `code_resolution_mode='identity'` (client opted in). DKE + Dothanh switched to `identity` mode (no Growatt-style regex pattern in goods_name); Growatt stays in `batch_aggregate_resolution` mode. Result post-correction: Growatt 3007/3182 internal_code populated (175 NULL await BQD), DKE 1272/1488 (216 NULL = customs missing in source), Dothanh 333/449 (116 NULL = customs missing in source). All NULLs are now intentional.

**Test cleanup:** removed `test_growatt_settlement_workbook_has_bcct_sheets` — that 51MB `.xlsm` is a CO/settlement workspace file (likely ERP transactions + RVC/LVC), not one of the 4 supported upload types (BCCT, DS NVL, DS SP, BOM). Out of MVP scope; addressing it later.

Test suite: 73 passed.

**2026-05-03 (PM) — Fixed all 5 parser bugs surfaced by the corpus.** P0: legacy `.xls` support via xlrd (magic-byte dispatch in `_excel.py`, thin xlrd→openpyxl adapter `_XlsBook`). P0: tightened BCCT gating (require `declaration_no` AND `registration_date`, ruling out BOM workbooks). P1: extended BOM aliases for Chinese (`成品物料/组件物料/标准用量/单位`) + SAP English (`Component number/Comp. Qty (CUn)/Component unit`). P1: materials parser accepts product_code-only catalogs (DS SP/TP files without `Mã HQ`). Bonus: extended IMPORT/EXPORT_TYPES with E21/E23/E31/E41, A11/A12/A41/A42, B11/B12/B13, G11-13/G21-23 (real Dothanh data uses E31, A12); added `Số TK`/`Ngày ĐK` short-form aliases (real abbreviated headers). Johnson SAP parser also fixed: was including parent ASM-001 as a row instead of skipping; now detects parent_level dynamically. Real-data validated: Growatt NK 3045 rows, Growatt XK 137 rows, DKE 2025 ~thousands, Dothanh E31 132 rows, E62 317 rows — all parse cleanly via `.xls` adapter.

**2026-05-03 (AM) — Real-data fixture corpus + parser-bug documentation.** Built `tests/fixtures/{manual_test,edge_cases}/` (26 files, 228 KB), `tests/test_fixture_corpus.py` (parametrized over 26 cases — 19 pass + 7 xfail), `tests/test_real_data_external.py` (env-gated for real `.xls`/big `.xlsm` data). Surfaced 5 distinct parser bugs (2 P0, 3 P1) — all logged as xfail tests so the suite is green but the bugs are tracked. Brief: `.ai/features/2026-05-03-parser-bugs.md`. Bugs: legacy `.xls` unsupported, BCCT parser falsely matches BOM workbook (197K junk rows on real Growatt 51MB BOM), Chinese BOM headers not aliased, SAP English headers not aliased (Johnson), SP-only catalog rejected.

**2026-05-02 — Settlement resolver ripped out of hub.** After critic review, removed BCQT-flavored canonical-code resolver from hub (was a lossy port of bcqt-growatt algorithm — wrong for TP today). Migration `009_rip_resolver.sql` drops `hub.code_mapping_resolutions` + `bcct_rows.resolved_customs_code`. Algorithm moved to `scripts/settlement_resolver.py` (CLI). DECISIONS entry "2026-05-02 Settlement code resolver moved out of hub". Brief: `.ai/features/2026-05-02-rip-resolver-from-hub.md`.

**2026-05-02 — RBAC + per-client ACL.** Feature brief: `.ai/features/2026-05-02-auth-rbac-acl.md`. Session: `.ai/sessions/2026-05-02-rbac-acl.md`. Pre-SSO phase: cross-app token issuer deferred until BCQT/CO consumers exist.

**2026-05-01 (full day):**
- `2026-05-01-autopilot-mvp-scaffold.md` — initial autopilot build of foundation, schema, auth, entity routers, JSON API, audit views.
- `2026-05-01-client-restructure-i18n-redesign.md` — post-autopilot UX iteration: DNCX→Clients rename, workspace mental model, breadcrumb, dual-source detection, BCCT payload capture, button restyle, i18n overhaul, settings page redesign.

## Next Steps

1. **Real BOM upload** — haven't driven any real BOM through HTTP yet. Need a real, in-scope BOM file (NOT the 51MB settlement workbook — that's out of MVP). Synthetic Chinese-headers BOM works at parser level. Find a real customer-submitted BOM, upload, verify dual-source flag flips for materials present in both BCCT + BOM.
2. **Real BQD (code mappings) upload** — also untested at HTTP level. Need to locate a real BQD file or build one from agency.
3. **Header-matching greediness** — substring-match in `index_headers` is too greedy on real Vietnamese files: `STT` matches `line_no` (via "stt" alias) but ALSO `currency` (via "tt" alias). `Mã ĐVT kiện` (package unit) matches `unit` ahead of `Đơn vị tính`. Fix: prefer exact match over substring; rank by alias specificity.
4. **DKE catalog category default** — real DKE NPL → category=nvl ✓, SP → also nvl (default fallback). Sheet name `Sheet1` doesn't carry category hint. Either add `category` Form param to upload route (UI selection) or filename-heuristic ("SP" in name → tp).
5. **DKE/Dothanh per-client goods_name parser.** Both clients are in `identity` mode (internal=customs) as a fallback; if their goods_name has structured codes worth extracting, add a per-client regex parser in `goods_name.py:internal_code_parser_for`.
6. **51MB Growatt `.xlsm`** — out of scope for MVP (likely ERP transactions + settlement workspace). Revisit after MVP if customer wants to ingest ERP-derived data.
3. **`code_resolution_mode` reparse-on-change** — dropdown unlocked for dev (2026-05-02) but POST handler doesn't auto re-parse `bcct_rows.internal_code` for existing rows when mode changes. Add `reparse_internal_codes(client_id, mode)` helper (~15 lines) and wire into POST `/clients/{id}/edit` when mode differs. Idempotent given deterministic parsers + raw `goods_name` preserved.
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

- **Server NOT running.** Start with `uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload`. Auto-seed runs on empty DB via lifespan hook. Set `DATA_HUB_AUTO_SEED_DEMO=0` to disable. Reset: `psql -d data_hub -c "truncate hub.clients cascade"`.
- **Migrations applied:** 001..009. Latest = 009 dropped resolver artifacts. Migration ledger in `hub.schema_migrations`.
- **Settlement resolver lives at `scripts/settlement_resolver.py`** as a CLI tool, NOT imported by `app/`. Hub schema does NOT have `code_mapping_resolutions` or `bcct_rows.resolved_customs_code`. Don't reintroduce — coupling is intentionally severed. When BCQT migrates to consumer mode, this script ports there + gets NVL/TP split fix per `bcqt-growatt/settlement/code_map.py`.
- **`scripts/seed_demo.py` deleted** in this commit — was rotting (HTTP-based, pointed at renamed `/dncxs` URLs). Auto-seed at lifespan superseded it.
- **RBAC enforcement layers:** Postgres CHECK + partial unique index (DB), `app/auth/permissions.py` helpers (app), Jinja `can_*` flags in templates (UI). DB is source of truth.
- **Single-dev invariant** enforced by `unique on hub.users((1)) where role='dev'`. Trying to create 2nd dev → `UniqueViolation`. The seed admin (`admin@data-hub.local`) is auto-promoted to `dev` by migration 008.
- **Vietnamese is default UI language**, English is toggle. `t()` Jinja callable, cookie `data_hub_lang`. Translation dict in `app/i18n.py` (~190 keys).
- **Mental model: Client first, then workspace.** All entity URLs nested under `/clients/{client_id}/{tab}`. No global "all materials across clients" view.
- **Code seed is `barry-CO-main` (capital CO)** at `~/workspace/client/barry-CO-main`.
- **Dual-source materials** detected at query time (EXISTS subqueries). NOT stored.
- **BCCT payload jsonb captures every source column** by original Vietnamese header. Typed columns are query/index layer; payload is raw archive.
- **CSS mostly inherited from CO** (`barry-CO-main/app/static/css/app.css`). Data Hub appended ~180 lines for breadcrumb, settings, admin pages, dual badge, dark theme.
- **Sister-repo cross-link decisions**: anchor architecture in `~/workspace/client/BCQT-System/.ai/DECISIONS.md` "2026-04-30 PM — Data Hub 3-app architecture" with 2026-05-01 BCCT-amendment block at top. Local DECISIONS adds 2026-05-02 entry for resolver rip-out.

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
  - `scripts/screenshot.py` — Playwright UI capture
  - `scripts/settlement_resolver.py` — CLI for BCQT-flavored canonical resolver (hub-runtime-isolated; destined for BCQT migration)
- Memory: `~/.claude/projects/-home-vp-workspace-client-data-hub/memory/`
  - `project_architecture_lock.md`, `project_bom_multisource.md`, `reference_co_codebase.md`
