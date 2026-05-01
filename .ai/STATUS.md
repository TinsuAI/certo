# Project Status

**Date:** 2026-05-02 — Tier 1 real-data smoke (BOM + BQD) closed. 4 parser/UX bugs logged.

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
- **109 pytest tests passing + 7 skipped** (real-data, env-gated). 0 xfail.
- With real-data dir set: +6 more passing (real `.xls` BCCT for Growatt/DKE/Dothanh + Growatt 51MB settlement workbook).
- Playwright screenshots in `data/screenshots/` (light + dark + EN + new ones for stages A+B / D / C1 / C2 / fix-toast).
- Fixture corpus at `tests/fixtures/` (18 manual `.xlsx` + 9 synthetic edge cases incl. 2 legacy `.xls`). Driven by `tests/test_fixture_corpus.py`.
- **Manual test fixtures at `data/manual_test/`** (4 .xlsx + README + cleanup SQL). Each file documented with its target URL + expected outcome.
- **`/admin/settings/technical`** (dev-only): LLM endpoint + auto-fetched model list dropdown + auto-default first model. After save → redirects with `?fetch_models=1`, populates dropdown from `GET {base_url}/models`.
- **BCCT row table** has `Lịch sử` column with `✏ N` badge linking to per-row history page; rows that have changed show event count + last-changed time.
- **Audit history page** resolves user_id → display_name + email; sentinels (`system`, `ops:script`) shown distinctly.
- **Upload preview/parse-mapping page** uses `<select>` dropdowns (not free text) populated from canonical 27-field BCCT logical-field list. 3 explicit decisions: Lưu / Reject / Quay lại sau. Reject path marks `parse_status='rejected'`. `/uploads` page links back to propose UI for `proposed_mapping` files.
- **Post-upload toast** on `/clients/{id}/bcct` shows ingest counts (NEW · UPDATED · DELETED · NOOP · SKIPPED).

## Recent Changes

**2026-05-02 — Tier 1 real-data smoke (BOM + BQD).** Session log: `.ai/sessions/2026-05-02-tier-1-real-data-smoke.md`. First end-to-end run of real BOM + BQD through the live UI (STATUS Next-Steps #1+#2). Approach: explore sister-repo data → stage `/tmp/dh_real_data/{company}/*` → parser-layer xfail-aware test → Playwright UI smoke with screenshots.
- **Real-data corpus staged** (6 new symlinks in `/tmp/dh_real_data/`): Growatt BOM TP/BTP + BQD TP/NVL, DKE BQD multi-sheet, Johnson SAP fixture.
- **Parser-layer test extended:** `tests/test_real_data_external.py` BOM + BQD blocks. Result with env: 9 passed + 5 xfailed. Suite green: 104 passed.
- **UI smoke script:** `scripts/smoke_real_uploads.py` (Playwright). 4/4 active jobs matched expectation; 1 intentionally skipped to avoid silent corruption.
- **DB verified:** Growatt 2900 BQD mappings (8 seed + 73 TP + 2819 NVL); Johnson 2 BOM versions; Growatt BOM TP errored cleanly.
- **4 bugs logged to `.ai/BACKLOG.md`** (Bug A / B / C / UX-1). Bug C is silent BOM data corruption (P0); Bug A blocks all real Growatt BOM today (P0); Bug B is a 1-line alias fix (P1); UX-1 is a raw-JSON error page (low).

**2026-05-04 EOD — UX iteration + manual-test fixtures + /rev follow-ups (~10 commits).** Session log: `.ai/sessions/2026-05-04-ux-iteration-and-rev-followups.md`. Triggered by user manual-testing the just-shipped 4 stages — surfaced 8 UX issues + minor /rev follow-ups, all fixed:
- Manual test fixtures at `data/manual_test/` (4 files + README + cleanup SQL); each clearly maps to its target URL + expected behavior.
- Post-upload toast (silent success was alarming): `?ingested=N&new=...&updated=...&deleted=...&noop=...&skipped=...` query string → green banner.
- LLM error sanitization v2: 3 distinct messages (LLM-disabled / call-failed / empty workbook) — `Detail withheld to avoid leaking credentials` was misleading when the real issue was misconfigured model name.
- LLM auto-fetch model list from `GET /v1/models`; auto-defaults the first model when user saves base_url + key (no more typing model names by hand).
- Prompt fix: "json" lowercase in messages (OpenAI strict-output rule rejected our prompt on real endpoint).
- Template bug: parse-mapping showed `samples[0][0] · samples[1][1]` for every column instead of column-specific values (col_idx capture).
- Logical-field input → `<select>` dropdown populated from canonical 27-field list, with `(skip)` option.
- Reject button on parse-mapping UI (3 explicit decisions instead of binary).
- `review mapping →` link from `/uploads` for files in `proposed_mapping` state.
- BCCT row table: new `Lịch sử` column with event-count badge linking to per-row history.
- History page actor column: resolves user_id → display_name + email; sentinels render as warn badge with tooltip.
- 3 ideas captured to `.ai/BACKLOG.md` (upload preview at all stages / catalog provenance / BCCT staleness metadata).
- /rev minor follow-ups #1 (`use_count` overcount) + #2 (FileNotFoundError on missing blob) fixed; #3 (migration numbering gap) intentionally deferred — renaming applied migrations risks `schema_migrations` divergence cross-environment.

Tests: 106 → 109 passed (+3 LLM `list_models` tests). Server live at `http://127.0.0.1:8754`.

**2026-05-04 — BCCT overhaul + LLM smart parser (4 stages, ~3000 LoC).** Brief: `.ai/features/2026-05-04-bcct-overhaul-and-llm-parsing.md` (discover → critic → synthesize → plan → tdd → ui+screenshot → rev). Five commits `365bfed` → `1d79247`.

- **A+B:** 12 CO-essential typed columns promoted from payload jsonb (`exporter_name/exporter_tax_code/consignee_name/incoterms/weight+unit/package_count+unit/invoice_date/departure_date/destination_code+name/transport_mode/exchange_rate`). Back-fill from existing 5119 rows. Year column converted to `GENERATED ALWAYS AS (EXTRACT(YEAR FROM registration_date)) STORED`; PK rebuilt; 5 covering indexes recreated. Year form field dropped — staff just picks file.
- **D:** LLM-driven smart parser fallback. New `hub.app_settings` (key/value/audit), `hub.parser_mappings` (cache by client_id+module+file_signature), `hub.llm_usage` (per-(date,client) budget). New `app/llm.py` (OpenAI-compat → Anthropic OAI shim / OpenAI / vLLM / Ollama). Settings UI at `/admin/settings/technical` (dev-only). Flow: rigid parse → if fail → cache lookup → if miss → LLM proposes → preview UI → staff confirms → mapping cached for future uploads. file_signature client-scoped, prevents cross-client cache poisoning. Hallucinated fields/headers dropped via schema validation.
- **C1:** Confirm-on-update gate. New `hub.upload_pending` (24h TTL via expires_at), `hub.bcct_row_history` (append-only audit log), AFTER UPDATE/DELETE trigger reading `app.user_id` GUC, `purge_expired_pending_uploads()` SQL fn. `app/database.py:connect(user_id=...)` plumbs the GUC via `set_config()` for audit attribution. Pre-flight diff classifies NEW/NOOP/DIFF/ORPHAN; orphans scoped to declarations in upload (per critic — partial re-upload of one declaration won't delete others). Single-use pending_id (DELETE...RETURNING in same tx). NEW-only flows skip preview entirely.
- **C2:** Per-row history page (`/clients/{id}/bcct/history/{txn_key}/{line_no}`). Ops bypass CLI `scripts/bcct_force_apply.py` writes directly with synthetic `app.user_id='ops:script'` so audit log captures the bypass actor.

Post-`/rev` fixes (commit `1d79247`):
- **Critical** data-loss bug: confirm path was re-classifying after filtering out unconfirmed DIFFs, turning them into new ORPHANs that `confirm_orphans=True` would then DELETE. Fixed: confirm path now applies stashed diff_summary directly without re-classification. Regression test added.
- **Critical** `_apply_bcct_rows` ran inserts and orphan-deletes in two separate transactions despite "all in one txn" docstring. Refactored to share one cursor.
- **Critical** LLM error message echoed raw OpenAI SDK exception to browser → potential API-key leak in transport-error strings. Fixed: log full exception server-side, surface only exception class name + generic message.

Test suite: **40 → 106 passed** (1 day, +66 new). Brief tracks all 4 stages + open follow-ups.

**2026-05-03 (EOD revised) — HTTP-route real-data run + correction round.** Drove all 5 real `.xls` BCCT files through `/clients/{id}/bcct/upload` (Growatt NK 3045 + XK 137, Dothanh E31 132 + E62 317, DKE 2025 1488 — total 5119 rows). Idempotent re-upload verified. DKE Danh Mục NPL+SP through `/clients/{id}/catalog/upload` — 45 materials. Dual-source: 44/45 DKE in BCCT, 3/4 Johnson.

Route-layer fixes landed: (1) declaration types extended H11-H13/H21-H23/C11-C12 (23 rows had `direction=NULL`); (2) materials parser fallback alias `Mã` for single-column Danh Mục files (DKE shape); (3) materials `status` normalizer (Vietnamese "Đã duyệt" / "Đang dùng" / "Chờ duyệt" → DB enum).

**Correction (after user feedback):** initial fix that fell back `internal_code = customs_code` when goods_name parser missed was *wrong* — internal_code (agency's ERP code) and customs_code (HQ-assigned) are distinct concepts. BCCT files don't carry internal_code; hub derives it via per-client parser. NULL is the correct state when the parser can't extract; staff/BQD maps it later. Reverted: route now does `internal_code = customs_code` ONLY when `code_resolution_mode='identity'` (client opted in). DKE + Dothanh switched to `identity` mode (no Growatt-style regex pattern in goods_name); Growatt stays in `batch_aggregate_resolution` mode. Result post-correction: Growatt 3007/3182 internal_code populated (175 NULL await BQD), DKE 1272/1488 (216 NULL = customs missing in source), Dothanh 333/449 (116 NULL = customs missing in source). All NULLs are now intentional.

**Test cleanup:** removed `test_growatt_settlement_workbook_has_bcct_sheets` — that 51MB `.xlsm` is the CO app's working workbook (staff processing CO requests in barry-CO-main's domain), not a hub upload artifact at all. Hub's 4 supported upload types are BCCT, DS NVL, DS SP, BOM. CO uses hub as read consumer (Danh Mục + BCCT) and writes back BOM modifications via API — the workspace file stays in CO.

Test suite: 73 passed.

**2026-05-03 (PM) — Fixed all 5 parser bugs surfaced by the corpus.** P0: legacy `.xls` support via xlrd (magic-byte dispatch in `_excel.py`, thin xlrd→openpyxl adapter `_XlsBook`). P0: tightened BCCT gating (require `declaration_no` AND `registration_date`, ruling out BOM workbooks). P1: extended BOM aliases for Chinese (`成品物料/组件物料/标准用量/单位`) + SAP English (`Component number/Comp. Qty (CUn)/Component unit`). P1: materials parser accepts product_code-only catalogs (DS SP/TP files without `Mã HQ`). Bonus: extended IMPORT/EXPORT_TYPES with E21/E23/E31/E41, A11/A12/A41/A42, B11/B12/B13, G11-13/G21-23 (real Dothanh data uses E31, A12); added `Số TK`/`Ngày ĐK` short-form aliases (real abbreviated headers). Johnson SAP parser also fixed: was including parent ASM-001 as a row instead of skipping; now detects parent_level dynamically. Real-data validated: Growatt NK 3045 rows, Growatt XK 137 rows, DKE 2025 ~thousands, Dothanh E31 132 rows, E62 317 rows — all parse cleanly via `.xls` adapter.

**2026-05-03 (AM) — Real-data fixture corpus + parser-bug documentation.** Built `tests/fixtures/{manual_test,edge_cases}/` (26 files, 228 KB), `tests/test_fixture_corpus.py` (parametrized over 26 cases — 19 pass + 7 xfail), `tests/test_real_data_external.py` (env-gated for real `.xls`/big `.xlsm` data). Surfaced 5 distinct parser bugs (2 P0, 3 P1) — all logged as xfail tests so the suite is green but the bugs are tracked. Brief: `.ai/features/2026-05-03-parser-bugs.md`. Bugs: legacy `.xls` unsupported, BCCT parser falsely matches BOM workbook (197K junk rows on real Growatt 51MB BOM), Chinese BOM headers not aliased, SAP English headers not aliased (Johnson), SP-only catalog rejected.

**2026-05-02 — Settlement resolver ripped out of hub.** After critic review, removed BCQT-flavored canonical-code resolver from hub (was a lossy port of bcqt-growatt algorithm — wrong for TP today). Migration `009_rip_resolver.sql` drops `hub.code_mapping_resolutions` + `bcct_rows.resolved_customs_code`. Algorithm moved to `scripts/settlement_resolver.py` (CLI). DECISIONS entry "2026-05-02 Settlement code resolver moved out of hub". Brief: `.ai/features/2026-05-02-rip-resolver-from-hub.md`.

**2026-05-02 — RBAC + per-client ACL.** Feature brief: `.ai/features/2026-05-02-auth-rbac-acl.md`. Session: `.ai/sessions/2026-05-02-rbac-acl.md`. Pre-SSO phase: cross-app token issuer deferred until BCQT/CO consumers exist.

**2026-05-01 (full day):**
- `2026-05-01-autopilot-mvp-scaffold.md` — initial autopilot build of foundation, schema, auth, entity routers, JSON API, audit views.
- `2026-05-01-client-restructure-i18n-redesign.md` — post-autopilot UX iteration: DNCX→Clients rename, workspace mental model, breadcrumb, dual-source detection, BCCT payload capture, button restyle, i18n overhaul, settings page redesign.

## Next Steps

1. **Fix Bug C (silent BOM corruption) + Bug A (header_row) together** — both in `app/parsers/_excel.py`. P0. Bug C is silent data corruption on real Growatt BTP via empty-cell substring match in `index_headers` pass 2; Bug A is `header_row()` picking data row over header row. Fixes likely overlap. See `.ai/BACKLOG.md` "Parser bugs surfaced by 2026-05-02 real-data smoke test".
2. **Fix Bug B** (DKE BQD alias gap) — 1-line addition to `app/parsers/code_mappings.py:11 ALIASES` (`Mã ERP`, `Mã NPL/TP`).
3. **Header-matching greediness** — substring-match in `index_headers` is too greedy on real Vietnamese files: `STT` matches `line_no` (via "stt" alias) but ALSO `currency` (via "tt" alias). `Mã ĐVT kiện` (package unit) matches `unit` ahead of `Đơn vị tính`. Fix: prefer exact match over substring; rank by alias specificity. *Probably resolved as part of Bug A+C fix; verify with same smoke test.*
4. **UX-1: BOM upload parse error renders as raw FastAPI JSON** — `app/routes/bom.py:85` raises HTTPException → browser shows `{"detail":"Parse error: ..."}`. Catch + render error template (or BCCT-style toast) instead.
5. **DKE catalog category default** — real DKE NPL → category=nvl ✓, SP → also nvl (default fallback). Sheet name `Sheet1` doesn't carry category hint. Either add `category` Form param to upload route (UI selection) or filename-heuristic ("SP" in name → tp).
6. **DKE/Dothanh per-client goods_name parser.** Both clients are in `identity` mode (internal=customs) as a fallback; if their goods_name has structured codes worth extracting, add a per-client regex parser in `goods_name.py:internal_code_parser_for`.
7. **51MB Growatt `.xlsm`** — CO app working workbook, not a hub upload type. Hub never ingests it; CO owns it.
8. **`code_resolution_mode` reparse-on-change** — dropdown unlocked for dev (2026-05-02) but POST handler doesn't auto re-parse `bcct_rows.internal_code` for existing rows when mode changes. Add `reparse_internal_codes(client_id, mode)` helper (~15 lines) and wire into POST `/clients/{id}/edit` when mode differs. Idempotent given deterministic parsers + raw `goods_name` preserved.
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

## Backlog

See `.ai/BACKLOG.md` for ideas captured but not yet planned. Top items:

- **Pre-commit upload preview at all stages** (catalog/bqd/bom — BCCT already half-done via parser-mapping flow).
- **Catalog with multi-source provenance** (DS HQ-registered vs auto-derived from BCCT vs user-uploaded). Most valuable: which codes are actually registered with HQ. Auto-derive from BCCT can show codes that appeared on declarations but aren't registered.
- **BCCT tab staleness metadata** (last upload date + most recent declaration date — two distinct signals).
- **Apply confirm-gate pattern to catalog/bqd/bom** (only BCCT has pre-flight diff today).
- **Manual mapping UI** when LLM is disabled (today: upload errors with no recourse).
- Migration numbering gap 010→012 (cosmetic; deferred — would need cross-env `schema_migrations` fixup).
- CSRF protection on POST endpoints (pre-existing project gap).
- `set_config('app.user_id', ..., true)` (LOCAL) when connection pooling lands.

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
