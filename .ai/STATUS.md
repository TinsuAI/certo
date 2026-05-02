# Project Status

**Date:** 2026-05-03

## Current State

Data Hub MVP web app: upload preview-confirm flows across all 4 modules (BCCT/BOM/BQD/Catalog), SSO/JWT auth, read APIs, BOM proposals, chat agent, CO-facing contract guardrails, slim `/client-config` master-data API + admin UI for declaration types/presets/per-client config, in-app notifications, BCCT confirm-on-update gate + history page, LLM smart parser for BCCT/BOM/BQD, catalog multi-source provenance, staleness banner across all 4 tabs, production deployment scaffold.

**New 2026-05-03:** Service-account JWTs shipped (auth: machine identities for sister-app integration). 239 passed, 15 skipped (+20 from baseline 219). Plus housekeeping: dev port 8754 pinned in AGENTS.md, BACKLOG trimmed (267→81 lines + JWT entry), CO migration status check posted (NOT STARTED, 14 days to sunset), data/screenshots/ untracked (37MB binary blobs gone from index).

## Recent Changes (2026-05-03)

6 commits this session:

- `9689210` docs: refresh STATUS + pin dev port + trim BACKLOG + flag CO migration not started
- `a47df52` auth: service-account JWTs for sister-app integration (migration 020, store, issuer extension, ACL branching, CLI, 20 tests, sister-app note)
- `77314be` docs: defer CO/BCQT service-account JWT adoption to BACKLOG
- `adb7aa2` fix(test): _cleanup.sql column rename product_code → internal_code
- `d7ae89d` chore: untrack data/screenshots, add confirm-gate demo script
- `18f29e2` chore: actually untrack data/screenshots blobs

For prior arcs (BCCT overhaul, Phase 1-3, Sprint A/B/C/D/E, API guardrails, Hướng B), see git log + `.ai/sessions/`.

## Next Steps

1. **CO migration cutover by 2026-05-16** — sister-app note status check (2026-05-02 PM): CO still on `/co-config` + old nested shape. 13 days remaining as of 2026-05-03. Needs CO repo agent to act before ~2026-05-12.
2. **BCQT one-line entry in DECISIONS.md** — point a BCQT agent at `.ai/sister-app-notes/2026-05-02-bcqt-client-config-available.md`.
3. **Schedule `/co-config` removal** — after CO confirms cutover, run `/schedule` per `.ai/scheduled/2026-05-16-remove-co-config.md`.
4. **CO + BCQT adopt service-account JWTs** — deferred to BACKLOG (no hard deadline; coexistence works). Pull out when ready to flip `api_auth_strict=true`.
5. Backlog items unchanged: CSRF, manual mapping UI when LLM disabled, BOM parse-error UX, migration numbering 010→012.

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
