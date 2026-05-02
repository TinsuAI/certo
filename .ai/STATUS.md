# Project Status

**Date:** 2026-05-02 (refreshed PM)

## Current State

Data Hub is a working MVP web app with upload preview-confirm flows, SSO/JWT auth, read APIs, BOM proposals, chat agent, CO-facing contract guardrails, and now a slim `/client-config` master-data API plus full UI for declaration-type catalog, presets, and per-client config. Latest full suite green: `219 passed, 15 skipped`.

Hướng B refactor (2026-05-02) shipped: CO-runtime config moved out of Data Hub responses, `co-config` deprecated with a 14-day grace window (Sunset 2026-05-16). Master data (declaration types, presets, fiscal year start month) is now in `hub.declaration_type_catalog`, `hub.client_type_presets`, `hub.client_config` — staff-editable, no hardcoded domain knowledge.

## Recent Changes

### Prior cycles (2026-05-01 → 2026-05-02 morning)

The 219-test surface didn't land in one sprint. Detail per arc in `.ai/sessions/`:

- **BCCT overhaul A+B/D/C1/C2 + post-/rev fixes** (`2026-05-04-bcct-overhaul-and-llm.md`, despite the filename the work is dated 2026-05-01 in commits `365bfed`..`1d79247`) — 12 typed CO columns, `year` as generated column, LLM smart parser with `parser_mappings` cache, confirm-on-update gate via `upload_pending` + `bcct_row_history` audit trigger, history page, ops escape hatch.
- **UX iteration after manual test** (`2026-05-04-ux-iteration-and-rev-followups.md`) — post-upload toast, LLM error sanitization, auto-fetch model list, `json` lowercase fix, sample column index bug, logical-field dropdown, reject path on parse-mapping, `/uploads` link to propose UI, history link from BCCT row table, user_id → email + display_name.
- **Tier 1 real-data smoke + Phase 1-3** (`2026-05-02-tier-1-real-data-smoke.md`) — parser bugs A/B/C/D fixed (commit `338be91`), universal preview-confirm pattern across all 4 modules (`359ebec`), LLM fallback for BOM/BQD via the same pipeline (`5d44b60`).
- **Visibility sprint A1-A4** (`2026-05-02-visibility-sprint.md`) — A2 LLM-fallback gate cement, A3 staleness bar across all 4 workspace tabs, A4 catalog multi-source provenance + audit alarm.
- **Sprint B + C + D + E** (autopilot run, see commits `692e5cf`..`b2642d6`) — B1 in-app notifications, B2 chat agent with strict ACL on every tool call, B3 SSO (Data Hub as JWT issuer), C1 LLM self-correction retry loop, C2 JWT auth on `/v1/hub/*` with permissive fallback, C3 chat agent extended with 3 more tools, D1 production deployment scaffold (M9 #6), E1+E2 catalog HQ-registered toggle + chat agent answer-row fix, E3 floating chat widget.
- **API guardrails** (`52aa9f2` + `4ab54e1` + `764474a` + `89b108a`) — CO contract guardrails, SSO authorize flow + API client ACL, source-summary + invoice-match endpoints, agent technical-enable toggle.

### Hướng B refactor — 2026-05-02

11 pieces, all tests green:

- **Piece 1 — Schema + seeds + stores.** Migration 019, seeds at `data/seeds/declaration_types.yaml` (20 codes) + `client_type_presets.yaml` (4 system presets). Stores in `app/stores/{declaration_types,client_type_presets,client_config}.py`. PyYAML added to deps. Idempotent seed loader at `app/seed_master_data.py`.
- **Piece 2 — Admin UI for declaration types.** `/admin/declaration-types` — list, add, inline edit, disable. Linked from `/admin/users` page header.
- **Piece 3 — Admin UI for presets.** `/admin/client-type-presets` — list, add, inline edit, delete (system presets refuse delete).
- **Piece 4 — Per-client config UI.** `/clients/{id}/declaration-config` — preset picker (snapshot semantics, no cascade), checkbox grid for declaration types, fiscal year selector. Audit-logged via GUC. Linked from `/clients/{id}/edit`.
- **Piece 5 — New endpoint.** `GET /v1/hub/dncxs/{id}/client-config` returning slimmed master-data shape with `config_version` + `config_hash`.
- **Piece 6 — Deprecate /co-config + changelog.** Old endpoint keeps serving with `Deprecation`, `Sunset`, `Link: rel="successor-version"` headers (RFC 8594). Master fields now sourced from `hub.client_config`. Created `docs/API_CHANGELOG.md` with first Breaking entry.
- **Piece 7 — Slim source-summary.** Dropped `co_stock_row_count` + `co_stock_row_count_semantics`. `client_config` sub-payload reshaped to match new `/client-config`.
- **Piece 8 — Notification trigger.** New `notify_api_contract_changed()` helper + `scripts/announce_breaking_change.py` CLI. Parses latest `## YYYY-MM-DD — Breaking:` heading from changelog, fans out to dev/admin users. Already fired for the 2026-05-02 entry.
- **Piece 9 — Backfill script.** `scripts/backfill_client_config_from_co.py` reads CO JSON files and seeds `hub.client_config`. Already applied: 2 clients backfilled (growatt-vn, do-thanh-vietnam-2614), johnson-vn skipped (already had a manual config from Piece 4 testing).
- **Piece 10 — Cross-repo notes.** Drafts in `.ai/sister-app-notes/` for CO + BCQT to action.
- **Piece 11 — Removal artifact.** `.ai/scheduled/2026-05-16-remove-co-config.md` documents what to delete on sunset day. NOT auto-scheduled — user runs `/schedule` if desired.
- **UX iteration after manual test feedback.** Checkbox grid CSS (`app.css`) — added `.checkbox-grid`/`.checkbox-cell` so import/export codes wrap across columns instead of cramming inline. Manual save (POST `/declaration-config`) now hardcodes `preset_key=None` so any hand-edit drops the preset link → state becomes "tự cấu hình". Apply-preset path is the only one that sets `preset_key`. Badge in zone-head shows current state ("Đang dùng preset: X" vs "Tự cấu hình").

Test count: 219 passed, 15 skipped (was 204 passed; +15 new in `tests/test_client_config.py`, plus rewritten `test_client_config_and_source_summary_endpoints`).

## Next Steps

1. **CO migration cutover by 2026-05-16** — sister-app note posted at `.ai/sister-app-notes/2026-05-02-co-migrate-to-client-config.md`; needs a ping to CO repo before ~2026-05-12 to verify cutover is in flight.
2. **BCQT one-line entry in DECISIONS.md** — point a BCQT agent at `.ai/sister-app-notes/2026-05-02-bcqt-client-config-available.md`.
3. **Schedule `/co-config` removal** — after CO confirms cutover, run `/schedule` to open removal PR per `.ai/scheduled/2026-05-16-remove-co-config.md`.
4. **Backfill johnson-vn** if needed — currently it has a `sxxk` config from manual testing; CO had it as `manual` with empty lists. Decide whether to overwrite from CO or leave the test config.
5. ~~Service-account JWTs~~ **shipped 2026-05-02 PM.** See
   `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`
   for CO/BCQT coordination. Test count: 232 passed, 15 skipped (+13
   new in `tests/test_service_account_jwts.py`).
6. **Flip `api_auth_strict=true`** — unblocked by #5 once CO + BCQT
   adopt service-account JWTs. No fixed deadline; can soak in staging
   first. See `BACKLOG.md` "API auth — flip dev-permissive reads".
7. Backlog items from earlier (CSRF, manual mapping UI, BOM parse-error UX, migration numbering) unchanged.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when user writes Vietnamese; user uses "tao" / responds with "ông"-"tôi".
- Master data is configurable, not hardcoded. New declaration types or DNCX activity-type presets go through the admin UI, not Python files. Seed YAML files (`data/seeds/`) are first-install only.
- Snapshot semantics on presets — never cascade preset edits to clients automatically. Re-apply is explicit.
- Sister-app coordination: every Data Hub API breaking change requires (a) entry in `docs/API_CHANGELOG.md` with `## YYYY-MM-DD — Breaking:` heading and (b) running `scripts/announce_breaking_change.py --confirm` to fan out the notification.
- The 2 trade-offs documented in `.ai/BACKLOG.md` (dev-permissive read auth, no service-account JWTs) are unchanged.
