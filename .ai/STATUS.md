# Project Status

**Date:** 2026-05-02 EOD — Phase 1+2+3 shipped (parser bug fixes + universal preview-confirm + LLM fallback for BOM/BQD).

## Current State

**Working MVP web app + read API + 4-role auth + universal preview pattern + LLM smart parser across all 4 upload modules.** Server should be up at `http://127.0.0.1:8754` (`--reload` mode). Login: `admin@data-hub.local / admin123` (role=`dev`).

What works (post Phase 1+2+3):
- Client management with workspace pattern (URLs nested under `/clients/{client_id}/{tab}`).
- 7+1 entity tabs per client: Overview, Catalog, BQD, BCCT, BOM, Proposals, Uploads, Staff (admin/manager-of-this-client only), Config.
- **Excel upload with universal preview-confirm for ALL 4 modules** (BCCT/BOM/BQD/Catalog): parse → stash to `upload_pending` → preview UI (sample rows + counters) → staff confirms or rejects → ingest.
  - BCCT keeps its richer NEW/UPDATED/DELETED/NOOP diff preview (with Phase 2 also routing all-NEW uploads through the gate, closing the prior bypass).
  - BOM/BQD/Catalog get sample-row + counter previews. BOM groups sample by product_code (top 5 × 4 rows each).
- **LLM smart parser fallback for BCCT (existing) + BOM + BQD (new in Phase 3).** Pattern: rigid parse fails → cache lookup → on miss, LLM proposes mapping → re-parse with override → preview → confirm caches mapping for future hits. Verified via synthetic English-headers BQD round-trip.
- **Curated parser aliases (post Phase 1).** `index_headers` is pass-1 exact match only — no substring fallback. Adding a new customer's header variant is a 1-line append to the relevant ALIASES list. Pass-2 substring was structurally unsafe (empty cell `'' in target` always True; short aliases like `'hq'` matched unrelated headers).
- **`header_row()` alias-aware scoring.** Picks the row with the most alias matches (≥2 threshold) over data rows that just have many populated cells. Fixed Bug A on real Growatt BOM TP/BTP.
- Code parser: extracts `internal_code` from BCCT `goods_name` at upload time (Growatt regex). Settlement-flavored canonical-code resolver moved out of hub on 2026-05-02 (CLI-only at `scripts/settlement_resolver.py`).
- BOM proposal queue: auto-only mode, 5-condition gate, idempotent.
- Public read API: 11 endpoints under `/v1/hub/*`, bearer-token auth.
- BCCT raw columns captured into `payload` jsonb (full Vietnamese headers preserved).
- Dual-source material detection: query-time EXISTS subqueries flag materials present in both BCCT imports + BOM products.
- i18n bilingual: Vietnamese default + English toggle (cookie). ~190 translation keys.
- Auto-seed on empty DB: creates Growatt VN + Johnson VN demo data.
- 4-role RBAC + per-client ACL (2026-05-02). `dev` / `admin` / `manager` / `staff`.
- **119 pytest tests passing with `DATA_HUB_REAL_DATA_DIR` set + 104+15skip without env. 0 xfail.**
- Playwright UI smoke at `scripts/smoke_real_uploads.py` (9-job matrix: BQD×3 + Catalog×2 + BOM×3 + BCCT×1, all jobs route through preview-confirm).
- Real-data corpus staged at `/tmp/dh_real_data/{growatt,dke,dothanh,johnson,manual_test}/`.
- Audit script `scripts/audit_pass2_deps.py` for future alias drift detection.
- LLM endpoint configured (`hub.app_settings`): vLLM at `http://192.168.1.88:2455/v1`, model `gpt-5.5`, daily budget 50/client.

DB state (post Phase 1-3 UI smoke):
- Growatt-vn: 2900 BQD mappings, 293 BOM versions / 23,897 rows / 212 distinct products, ~2-3 catalog materials added via preview
- DKE-vn: 242 BQD mappings (NEW from Bug B fix)
- Johnson-vn: 2 BOM versions (synthetic SAP fixture)
- 5119 BCCT rows from earlier sessions remain.

## Recent Changes

**2026-05-02 EOD — Phase 1+2+3 shipped (~2,400 LoC, 4 commits, autopilot run).** Session log: `.ai/sessions/2026-05-02-phase-1-3-parser-and-preview.md`. Feature brief: `.ai/features/2026-05-02-universal-preview-and-parser-fixes.md`.

- **Phase 1** (commit `338be91`): rigid parser fixes — Bug A (header_row picks data row), Bug B (DKE BQD alias gap), Bug C (silent empty-cell substring corruption — DROPPED pass-2 entirely; promoted 4 production substring deps to explicit pass-1 aliases per `scripts/audit_pass2_deps.py`), Bug D (`_cat_from_sheet` BTP-before-TP). All 5 xfails converted to positive assertions with regex-shape guard.
- **Phase 2** (commit `359ebec`): universal preview-confirm pattern across all 4 modules. BOM/BQD/Catalog get sample-row+counter previews; BCCT all-NEW now also routes through the existing confirm-on-update gate. /rev fixes: BOM partial-commit (load pending → create versions → THEN delete pending; previously deleted-first was racy on failure), `expires_at > now()` guard on confirm SELECTs, defensive `connect(user_id=...)` plumbing, fixed nonexistent CSS class names.
- **Phase 3** (commit `5d44b60`): LLM fallback for BOM + BQD via the Phase 2 preview pipeline. New `app/routes/_llm_fallback.py` with shared helpers (lookup_cached_mapping, request_llm_mapping, cache_confirmed_mapping). Parsers got `mapping_override` kwarg. Verified end-to-end via synthetic English-headers BQD: rigid raised → LLM mapped Internal/Customs/Note → re-parsed → preview → 3 rows.
- **Tooling pre-commit** (commit `2658468`): real-data smoke corpus + Playwright UI smoke + pass-2 audit script + 19 screenshots.

**2026-05-02 — Tier 1 real-data smoke (BOM + BQD).** Session log: `.ai/sessions/2026-05-02-tier-1-real-data-smoke.md`. Discovery work that surfaced the 4 bugs.

**2026-05-04 EOD — UX iteration + manual-test fixtures + /rev follow-ups (~10 commits).** Session log: `.ai/sessions/2026-05-04-ux-iteration-and-rev-followups.md`.

**2026-05-04 — BCCT overhaul + LLM smart parser (4 stages, ~3000 LoC).** Brief: `.ai/features/2026-05-04-bcct-overhaul-and-llm-parsing.md`. Built the LLM infrastructure (`app/llm.py`, `hub.parser_mappings`, `/admin/settings/technical` UI) that Phase 3 above re-used.

(See git log + prior session logs for older history.)

## Next Steps

Five follow-ups from the autopilot Phases 1-3 + earlier backlog:

1. **BCCT LLM-fallback bypasses diff-preview gate** (pre-existing, surfaced in Phase 3 /rev). `parse_mapping_confirm` calls `_apply_bcct_rows` directly instead of going through `_ingest_rows` → no diff vs DB check after staff confirms LLM mapping. **Fix:** route LLM-confirmed parse through `_ingest_rows` (now always stashes for preview).
2. **Focused unit tests for `header_row` + `index_headers` edge cases** (deferred from Phase 1 /rev). Real-data tests cover the production path; need positive unit tests for: alias-match scoring with 1-match-only fallback, claim-once enforcement, `aliases=None` fallback path.
3. **Refactor: shared upload_pending helper module.** 3 module preview/confirm/reject route trios (~150 LoC each) are duplicated across `bom.py`, `bqd.py`, `catalog.py`. Defer until 5th customer forces shape change.
4. **`normalize_header` caching for BCCT-scale workbooks** (deferred from Phase 1 /rev). Phase 2 preview path re-parses files at preview AND confirm time, doubling the cost. Cache `normalize_header(headers)` once per sheet.
5. **`expires_at` guard on GET preview_view routes** (low priority). Currently relies on lifespan-scheduled `purge_expired_pending_uploads()`. A race could let a stale pending be confirmed.

Earlier-still backlog (see `.ai/BACKLOG.md`):
6. **Catalog multi-source provenance** (DS NVL/SP ĐK HQ vs auto-derived from BCCT vs user-uploaded; surface "on declaration but not registered").
7. **BCCT tab staleness metadata** (last upload date + most recent declaration date).
8. **CSRF protection on POST endpoints** (pre-existing project gap).
9. **`set_config('app.user_id', ..., true)` LOCAL** when connection pooling lands.
10. **Cross-app SSO Phase 2** (M9 deliverable #4) — JWT issuer / JWKS / cookie-domain federation when BCQT and CO consumers come online. Defer until BCQT/CO migration audits land.
11. **Production deployment** (M9 deliverable #6) — systemd, pg_dump backup pipeline, Litestream for per-project SQLite (BCQT-side), nginx reverse proxy.
12. **JWT scope auth on read API** — currently accepts any non-empty bearer token; phase 2 adds proper JWT scope validation.
13. **Audit log UI for permission changes** — `granted_by`/`granted_at` columns are populated; an admin-side history view is deferred.
14. **Password reset / invite email / 2FA** — current admin creates user with chosen password directly; phase 2 should add reset flow, invite emails, optional 2FA.
15. **Migration numbering 010→012 cosmetic gap** (intentionally deferred — would need cross-env `schema_migrations` fixup).

## Blockers

None. Production-ship gates: SSO design + deployment shape + remaining /rev follow-ups (1-5 above are quality-of-life, not blockers).

## Notes for Next AI Session

- **Server may still be running** at `:8754` with `--reload`. Background task ID `b2da6aqrc` from this session. Hot-reload picks up changes to `app/`. Restart cleanly with `pkill -f 'uvicorn app.main' && uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload`.
- **`hub.app_settings` LLM config is live** — vLLM endpoint at `192.168.1.88:2455`, model `gpt-5.5`, budget 50/day/client. To test LLM fallback without hitting the endpoint, build a synthetic file with non-aliased headers and check the `proposed_by` field on the resulting `upload_pending` row.
- **`hub.parser_mappings` empty before Phase 3 testing** — first LLM-fallback runs will populate it. Cache hits show as `proposed_by='llm_cached'` in preview pending.
- **Real-data corpus** at `/tmp/dh_real_data/`. Ephemeral (symlinks). Re-create by re-staging from sister repos (paths in `.ai/sessions/2026-05-02-tier-1-real-data-smoke.md`).
- **`/tmp/dh_real_data/manual_test/bcct_baseline.xlsx`** is a smoke fixture symlink → `data/manual_test/03a_stage_C1_baseline.xlsx`. Smoke uses MAN_C1_* transaction keys to avoid colliding with real BCCT data.
- **DB has stale 5119 BCCT rows from earlier sessions** + 3 MAN_C1 rows from Phase 2 smoke. Wipe with `delete from hub.bcct_rows where transaction_key like 'MAN_C1_%'` before re-running BCCT smoke.
- **Adding a new customer's header variant** is now a 1-line append to the relevant ALIASES list (Bug B style), or LLM fallback handles it automatically with mapping cached for future uploads. The audit script (`scripts/audit_pass2_deps.py`) helps validate that an alias addition doesn't shadow another field.
- **Vietnamese is default UI language**; English toggle via cookie. `t()` Jinja callable in `app/i18n.py`.
- **Mental model: Client first, then workspace.** All entity URLs nested under `/clients/{client_id}/{tab}`. No global "all materials across clients" view.
- **Code seed is `barry-CO-main` (capital CO)** at `~/workspace/client/barry-CO-main`.
- **Sister repos:** `~/workspace/client/BCQT-System` (settlement, future consumer), `~/workspace/client/barry-CO-main` (CO, code seed), `~/workspace/client/bcqt-growatt` (Growatt reference data).
- **Settlement resolver lives at `scripts/settlement_resolver.py`** as CLI tool, NOT imported by `app/`. Hub schema does NOT have `code_mapping_resolutions` — coupling intentionally severed (2026-05-02 decision).
- **Universal preview pattern caveat: BCCT 2-stage UI not yet unified.** BCCT has its own parse-mapping page (LLM column-mapping confirm) + diff-confirm page. BOM/BQD/Catalog use single Phase 2 preview. Unifying BCCT to the same single-preview shape is a follow-up refactor, not a current priority.

## Backlog

See `.ai/BACKLOG.md` for ideas captured but not yet planned. Updated 2026-05-02 with the 4 parser bugs (now closed) + cross-cut /rev items still open.

## Reference

- Sister repos:
  - `~/workspace/client/BCQT-System` — settlement product, future consumer of Data Hub
  - `~/workspace/client/barry-CO-main` — origin certificate product, code seed
  - `~/workspace/client/bcqt-growatt` — Growatt reference data + N-N mapping algorithm port
- Local design docs:
  - `.ai/DECISIONS.md` — local architecture decisions log
  - `.ai/features/2026-04-30-data-hub-mvp.md` — original discovery brief (3 critique rounds + amendments)
  - `.ai/features/2026-05-01-data-hub-read-api.md` — read-API contract design (v2)
  - `.ai/features/2026-05-04-bcct-overhaul-and-llm-parsing.md` — BCCT 4-stage build (LLM infra origin)
  - `.ai/features/2026-05-02-universal-preview-and-parser-fixes.md` — Phase 1-3 brief
  - `.ai/sessions/` — dated session summaries
- Demo + dev:
  - `scripts/screenshot.py` — Playwright UI capture (light + dark)
  - `scripts/smoke_real_uploads.py` — Playwright UI smoke for real-data uploads (9-job matrix)
  - `scripts/audit_pass2_deps.py` — alias-drift audit tool
  - `scripts/settlement_resolver.py` — CLI for BCQT-flavored canonical resolver
- Memory: `~/.claude/projects/-home-vp-workspace-client-data-hub/memory/`
  - `project_architecture_lock.md`, `project_bom_multisource.md`, `reference_co_codebase.md`
