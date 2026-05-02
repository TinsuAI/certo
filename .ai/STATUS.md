# Project Status

**Date:** 2026-05-02

## Current State

Data Hub is a working MVP web app with upload preview-confirm flows, SSO/JWT auth, read APIs, BOM proposals, chat agent, CO-facing contract guardrails, and now a slim `/client-config` master-data API plus full UI for declaration-type catalog, presets, and per-client config. Latest full suite green: `218 passed, 15 skipped`.

Hướng B refactor (2026-05-02) shipped: CO-runtime config moved out of Data Hub responses, `co-config` deprecated with a 14-day grace window (Sunset 2026-05-16). Master data (declaration types, presets, fiscal year start month) is now in `hub.declaration_type_catalog`, `hub.client_type_presets`, `hub.client_config` — staff-editable, no hardcoded domain knowledge.

## Recent Changes (Hướng B refactor — 2026-05-02)

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

Test count: 218 passed, 15 skipped (was 204 passed; +14 new in `tests/test_client_config.py`, plus rewritten `test_client_config_and_source_summary_endpoints`).

## Next Steps

1. **CO migration PR** — point a CO agent at `.ai/sister-app-notes/2026-05-02-co-migrate-to-client-config.md`. CO must cut over by 2026-05-16.
2. **BCQT one-line entry in DECISIONS.md** — point a BCQT agent at `.ai/sister-app-notes/2026-05-02-bcqt-client-config-available.md`.
3. **Schedule `/co-config` removal** — after CO confirms cutover, run `/schedule` to open removal PR per `.ai/scheduled/2026-05-16-remove-co-config.md`.
4. **Backfill johnson-vn** if needed — currently it has a `sxxk` config from manual testing; CO had it as `manual` with empty lists. Decide whether to overwrite from CO or leave the test config.
5. Backlog items from earlier (auth strict promotion, service-account JWTs, etc.) unchanged.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when user writes Vietnamese; user uses "tao" / responds with "ông"-"tôi".
- Master data is configurable, not hardcoded. New declaration types or DNCX activity-type presets go through the admin UI, not Python files. Seed YAML files (`data/seeds/`) are first-install only.
- Snapshot semantics on presets — never cascade preset edits to clients automatically. Re-apply is explicit.
- Sister-app coordination: every Data Hub API breaking change requires (a) entry in `docs/API_CHANGELOG.md` with `## YYYY-MM-DD — Breaking:` heading and (b) running `scripts/announce_breaking_change.py --confirm` to fan out the notification.
- The 2 trade-offs documented in `.ai/BACKLOG.md` (dev-permissive read auth, no service-account JWTs) are unchanged.
