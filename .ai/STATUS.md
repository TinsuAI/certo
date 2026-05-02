# Project Status

**Date:** 2026-05-03 (PM)

## Current State

Data Hub MVP web app: upload preview-confirm flows across all 4 modules (BCCT/BOM/BQD/Catalog), SSO/JWT auth, read APIs, BOM proposals, chat agent, CO-facing contract guardrails, slim `/client-config` master-data API + admin UI for declaration types/presets/per-client config, in-app notifications, BCCT confirm-on-update gate + history page, LLM smart parser for BCCT/BOM/BQD, catalog multi-source provenance, staleness banner across all 4 tabs, production deployment scaffold, service-account JWTs.

**New 2026-05-03 PM:** Technical-BOM flattening shipped (`technical_flatten` upload profile + flatten engine + UOM model + dual-source variants + staff-confirm gates + API hardening). 295 passed, 15 skipped (+56 from morning baseline 239). Six commit-shaped slices, each independently green. CO migration sister-app note posted at `.ai/sister-app-notes/2026-05-03-bom-flatten-shipped.md`.

## Recent Changes (2026-05-03)

PM session — BOM flattening (single feature shipped across 6 logical slices, will commit as one or two atomic commits depending on review):

- migration 021 (bom_versions structured identity + bom_unresolved_nodes + bom_flatten_decisions + UOM canonical/aliases/client overrides; 295 backfilled rows tagged `flatten_status='not_applicable'`)
- `app/flatten/` pure flattener core (engine, classify, graph cycle detect, UOM, identity, types — 31 unit tests)
- store integration (`app/stores/uom.py`, `app/stores/flatten_decisions.py`, extended `app/stores/bom.py` with `create_flattened_version_set`, `latest_flattened_versions`, BCCT/catalog/DB-BTP lookup builders — 12 store tests)
- upload route (new `technical_flatten` profile + flatten-preview template + confirm route with publish_filter — 4 upload tests)
- API hardening (`/v1/hub/products/{p}/bom/latest` filters `flatten_status`; 409 on dual-source variants; `get_version_with_rows` extended — 5 API tests + 4 identity tests)
- docs: `docs/API_CONTRACT.md`, `.ai/features/2026-05-03-bom-flattening.md`, `.ai/sister-app-notes/2026-05-03-bom-flatten-shipped.md`

AM session (already committed):

- `b6db3d5` handoff: session log + STATUS refresh for 2026-05-03
- `9689210` docs: refresh STATUS + pin dev port + trim BACKLOG + flag CO migration not started
- `a47df52` auth: service-account JWTs for sister-app integration

For prior arcs see git log + `.ai/sessions/`.

## Next Steps

1. **CO migration cutover by 2026-05-16** — sister-app note status check (2026-05-02 PM): CO still on `/co-config` + old nested shape. 13 days remaining as of 2026-05-03. Needs CO repo agent to act before ~2026-05-12. Now also blocks on flatten-aware BOM consumption per `.ai/sister-app-notes/2026-05-03-bom-flatten-shipped.md`.
2. **BCQT settlement consumer must adopt flatten contract** — when BCQT migrates to consume Data Hub BOM, it MUST handle the `non_flattened` filter + `409 dual_source_variants` per the new sister-app note.
3. **BCQT one-line entry in DECISIONS.md** — point a BCQT agent at `.ai/sister-app-notes/2026-05-02-bcqt-client-config-available.md`.
4. **Schedule `/co-config` removal** — after CO confirms cutover, run `/schedule` per `.ai/scheduled/2026-05-16-remove-co-config.md`.
5. **CO + BCQT adopt service-account JWTs** — deferred to BACKLOG (no hard deadline).
6. **Real-data smoke for Growatt BOM via technical_flatten** — gated behind DATA_HUB_REAL_DATA_DIR. Run when Growatt BTP/TP fixtures are at hand to verify flatten engine on real Chinese-SAP-shape workbooks.
7. Backlog items unchanged: CSRF, manual mapping UI when LLM disabled, BOM parse-error UX, migration numbering 010→012.

## Blockers

None.

## Notes for Next AI Session

- **Dev port 8754 is non-negotiable** (CO JWT iss validation depends on it). Now documented in AGENTS.md "Build & Run" section.
- **Dev server may still be running** at `127.0.0.1:8754` (started this session). Check `pgrep -f 'uvicorn app.main'` before starting another.
- **STATUS.md / BACKLOG.md historically lag HEAD by 30+ commits.** Verify code state before recommending work — git log + read code, don't trust the docs (saved as memory `feedback_verify_status_vs_code.md`).
- **`data/screenshots/` is gitignored.** All script-generated; regenerate via `scripts/screenshot.py` (basic UI), `scripts/smoke_real_uploads.py` (real-data smoke), or `scripts/demo_confirm_gate.py` (preview-confirm UX).
- **Service-account JWT design:** authorization comes from registry (`hub.service_accounts`), not the token. Admin-tightening scopes/client_ids takes effect immediately; verifier re-derives on every call. Token is authentication only.
- **Manual test fixtures** at `data/manual_test/` (12 XLSX + cleanup SQL + README walkthrough). `_cleanup.sql` only touches `MAN_*` rows — safe.
- Respond in Vietnamese with full accents when user writes Vietnamese; user uses "tao" / responds with "ông"-"tôi".
