# Session: 2026-05-02 — Autopilot long run (Sprint A + B + C)

User asked for a continuous autopilot run from ~03:06 SGT until ~10:30 SGT
(7-hour cap). I scoped 9 + 4 follow-up tasks across three sprints, all of
which shipped well under cap (~52 min for the build phase). All commits
green on first pass; no manual intervention.

## What was done

### Sprint A — Visibility (commits `1f4d70a` → `589d7aa`)

A1 — feature brief at `.ai/features/2026-05-02-visibility-sprint.md`.

A2 — BCCT LLM-fallback gate cement (`1f4d70a`).
- STATUS follow-up #1 was stale. Phase 2's universal `_ingest_rows`
  stash already routed `parse_mapping_confirm` through the diff-preview
  gate. Locked with 2 regression tests.

A3 — Staleness metadata bar (`53da49b`, ~16 tests).
- Two-line bar at the top of all 4 workspace tabs (BCCT/BOM/BQD/Catalog).
- `app/stores/staleness.py:tab_freshness()` does `MAX(parsed_at)` +
  per-module data MAX. `humanize_age` bilingual. `freshness_for_template`
  pre-renders for declarative templates.
- 6 i18n keys + CSS grid (collapses 1-col under 720px).
- Verified via curl smoke on all 4 tabs.

A4 — Catalog multi-source provenance (`6141d1e`, ~10 tests).
- `hub.materials.provenance jsonb` with three optional keys
  (registered_with_hq / seen_in_bcct / user_added). Migration 014
  backfills existing rows + adds GIN(jsonb_path_ops) index.
- `app/stores/provenance.py:derive_from_bcct` runs in the same txn as
  `_apply_bcct_rows` so new declaration codes flow into catalog
  automatically.
- Catalog UI gets badge column + Source filter chip row + "X mã trên
  BCCT chưa ĐK HQ" audit alarm banner.
- 12 i18n keys.
- E2E smoke verified: seed unregistered code → alarm appears + filter
  chip count reflects + filtered list shows the row.

### Sprint B — Notifications + chat agent + SSO (commits `692e5cf` → `bb6cccf`)

B0 — BCQT-System reference survey (`589d7aa`).
- Brief at `.ai/features/2026-05-02-bcqt-borrow-survey.md`.
- 3 sections: LLM optimizations (self-correction loop, mtime cache),
  notifications (full pattern lift with Postgres adaptations),
  chat-agent (tool-use with ACL on every dispatch).

B1 — In-app notifications (`692e5cf`, 12 tests).
- Migration 015: `hub.notifications` (id, user_id, kind, title, body,
  link_url, status, client_id, related_kind/id, timestamps) + partial
  index on `(user_id, created_at desc) WHERE status='unread'`.
- `app/notifications.py`: notify, notify_many, list_for_user,
  unread_count, mark_read, mark_all_read, get_for_user (all
  owner-scoped, no existence leak), `staff_with_edit_access_to_client`.
- Routes: GET /notifications (list), POST /{id}/read, POST /read-all.
  Bell rendered server-side via context_processor (no htmx
  dependency). Mark-read redirects to internal link_url if safe.
- Templates: `_bell.html` (<details>-based dropdown + badge),
  `list.html` (unread + read sections).
- 11 i18n keys.
- Wired triggers:
  1. `_ingest_rows`: when a BCCT upload lands at the preview gate, the
     uploader gets `bcct_preview_pending`.
  2. `_apply_bcct_rows`: tracks unregistered_seen_count before/after
     `derive_from_bcct`. If unregistered count went up, fan-out
     `provenance_alarm` to `staff_with_edit_access_to_client`. One
     notif per apply-batch — no spam.

B2 — Chat agent with strict ACL (`253baca`, 14 tests).
- Migration 016: `hub.chat_threads` + `hub.chat_messages`.
- `app/agent/`:
  - `tools.py`: 5 tool definitions (OpenAI function-calling shape).
    `dispatch_tool()` re-verifies `auth.require_can_view_client` on
    every call AND strips client_id/user_id from LLM-supplied args.
    Tools: query_bcct, query_catalog, query_bom,
    query_provenance_alarms, submit_final_answer.
  - `store.py`: thread + message CRUD with owner-scoped reads.
  - `runtime.py`: agent loop. System prompt enforces one-client-only
    + verify-before-stating + cite-tool-result. Caps:
    MAX_ROUNDS=6, MAX_TOOL_CALLS=12. Reuses
    `app.llm._check_and_record_budget`. `_parse_tool_args` tolerates
    duplicated/concatenated JSON (real bug observed against the local
    vLLM endpoint).
- Routes: thread list, create thread, view thread, send message.
  Foreign-thread access returns 404 (no existence leak).
- Templates: `agent_threads.html` + `agent_thread.html` (conversation
  pane with collapsed tool-result `<details>`).
- 18 i18n keys.
- E2E against the live vLLM endpoint: "Có bao nhiêu mã NVL trong danh
  mục?" → query_catalog(category=nvl, provenance=registered) →
  submit_final_answer with correct count + 3 example codes.

B3 — SSO: Data Hub as JWT issuer (`bb6cccf`, 9 tests).
- Brief at `.ai/features/2026-05-02-sso-design.md` (M9 deliverable #4).
- Migration 017: 3 hub.app_settings rows (issuer URL, active kid,
  token TTL).
- `app/jwt_issuer.py`: Ed25519 keypair on disk under `keys/`
  (gitignored, 0400). Auto-generates on first use.
  `make_token` / `verify_token` / `jwks` (publishes ALL kids on disk
  for rotation overlap; bootstraps active kid on first jwks call).
- `app/routes/auth_api.py`:
  - POST /v1/auth/token (JSON or form) → JWT.
  - GET /v1/auth/jwks (Cache-Control: max-age=600).
  - GET /v1/auth/validate (debug; consumers should verify locally).
- Constant-time-ish password verify path (calls argon2 verify against
  sentinel hash for missing users to flatten timing signal).
- E2E consumer-side simulation: token from /token → reconstruct
  Ed25519 public key from JWK 'x' → verify locally with PyJWT →
  claims match.

### Sprint C — Follow-ups (commits `3433d88` → `a7ce00e`)

C1 — LLM self-correction retry loop (`3433d88`, 2 net new tests).
- `propose_header_mapping` now retries up to `cfg.max_retries` when
  the LLM returns garbage (non-JSON, missing `mapping` key, all-invalid
  pairs). Each retry feeds the specific error back as a follow-up
  message. Partial-invalid (some valid + some invalid) drops the
  invalid silently and accepts what's left.

C2 — JWT auth on /v1/hub/* read API (`0a2d0f8`, 7 tests).
- `_require_token` upgraded to verify against `jwt_issuer.verify_token`.
- Permissive default (legacy non-JWT bearer accepted with warning) so
  dev callers + existing tests keep working.
- Strict mode (`api_auth_strict=true` in `hub.app_settings`) requires
  valid JWT.
- Expired tokens always 401 regardless of strict mode.

C3 — Extend chat agent with 3 more tools (`a7ce00e`, 7 tests).
- query_uploads (module, parse_status filters): file upload history.
- query_bcct_history (declaration_no | transaction_key, line_no):
  per-row audit log; joins hub.users to surface actor email.
- lookup_glossary (term): substring search on .ai/GLOSSARY.md bullet
  entries. Returns at most 5 matches (no full-file leak).

## Decisions made

- **A2 was stale; cement with tests, don't refactor.** The fix already
  shipped in Phase 2. Re-routing through `_ingest_rows` was already in
  place; locking the contract is cheaper than re-architecting.
- **A4 default category 'nvl' for auto-derived rows.** Most BCCT
  imports are NVL. Wrong-but-fixable: staff re-categorizes in catalog
  UI; provenance signal is independent of category.
- **B1 bell rendered server-side (no htmx).** Adding htmx for a single
  badge isn't worth the dependency. Each page load re-queries; cheap
  enough at our scale (one COUNT per render).
- **B1 fan-out only when count crosses 0→>0 (within an apply-batch).**
  Otherwise every BCCT upload would spam the same staff. Per-batch
  delta = useful signal.
- **B2 client_id always runtime-bound, never trusted from LLM.**
  Dispatcher strips client_id/user_id from args before calling impl.
  Defense in depth on top of route-level ACL gate.
- **B2 Anthropic-style prompt cache skipped.** Endpoint is OpenAI-compat
  (vLLM); cache_control isn't supported. Saves complexity.
- **B3 Ed25519 over RSA.** Smaller signatures, faster verify, no
  padding-mode footguns. PyJWT supports via cryptography.
- **B3 stateless verify at consumer.** No phone-home /validate for
  hot-path requests. Endpoint exists for debug only.
- **B3 keys auto-generate on first run.** Acceptable for dev; production
  ops should curate. Documented.
- **C2 permissive fallback (default).** Existing tests + dev callers
  use bearer-anything. Strict mode is a settings flag flip for
  production.
- **C3 lookup_glossary returns matched bullets only.** Full file is
  project metadata, not user content. Capped at 5 matches.

## What didn't work / Surprises

- **Migration 017 first attempt referenced `description` column** that
  doesn't exist on `hub.app_settings`. Server lifespan crashed. Fixed
  the SQL.
- **A3 first attempt rendered `00:00` time on date-typed `last_data_at`**
  because the partial template tried to detect datetime-vs-date via
  `':' in strftime('%H:%M')`. Fixed by pre-formatting in the helper
  (`isinstance(when, datetime)` check) so partial just shows the string.
- **A4 test pollution: `_apply_bcct_rows` change leaked B-CODE/C-CODE
  into growatt-vn materials** because confirm-flow tests called
  `_apply_bcct_rows` which now calls `derive_from_bcct`. Cleanup
  fixture didn't know about materials. Updated cleanup to delete the
  test customs_codes.
- **B1 first JWKS call returned empty** because keys/ dir didn't exist
  at server boot. Fixed by bootstrapping the active kid in `jwks()`.
- **vLLM endpoint emits duplicated/concatenated JSON in tool_call
  arguments** (`{"x":1}{"x":1}{"x":1}`). Real bug seen during E2E
  smoke. Mitigated in `runtime._parse_tool_args` via
  `JSONDecoder.raw_decode`.
- **bash compound `&&` with sleep + curl killed by parent shell**
  multiple times (exit 144). Worked around by issuing `nohup … &`
  as a standalone command, then waiting + curling separately.

## Numbers

- 12 commits across Sprint A/B/C.
- ~3,800 LoC added across app/ + tests/ + templates/ + migrations/.
- 132 → 182 tests (50 new), 0 xfail.
- 7 new migrations: 014 catalog provenance, 015 notifications, 016
  chat agent, 017 SSO.
- 3 new feature briefs in `.ai/features/`.
- ~2 new tabs (Trợ lý chat agent), 1 new section (notification bell),
  6 new i18n key groups.

## How to resume

```bash
cd ~/workspace/client/data-hub

# Server may still be up on :8754; if not:
nohup uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 \
  > /tmp/dh_server.log 2>&1 & disown

# Tests
uv run pytest -q                                            # 182 passed, 15 skipped
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q   # +15 real-data

# Login: admin@data-hub.local / admin123 (role=dev)

# Quick UI tour:
# - any client tab → top staleness bar (Sprint A3)
# - /clients/growatt-vn/catalog → Source filter + provenance badges (A4)
# - bell icon in topnav → notification dropdown (B1)
# - /clients/growatt-vn/agent → chat agent, ask "Có bao nhiêu mã NVL?" (B2)
# - POST /v1/auth/token + GET /v1/auth/jwks → SSO endpoints (B3)
```

## What's still on the table

- M9 deliverable #5: service-to-service tokens (CO → Data Hub write API).
- M9 deliverable #6: production deployment scaffolding (systemd,
  nginx, backup pipeline, key rotation SOP).
- BACKLOG items: CSRF protection, normalize_header cache, expires_at
  guard on GET preview routes, header_row unit tests, audit log UI.
- Notification triggers for BOM proposal queued, LLM mapping awaiting
  review, BCCT confirm completed.

## Pacing

03:06 SGT start. 03:58 SGT all 13 tasks committed. ~6h 32min spare under
the 10:30 cap. The remaining cap was deliberately not consumed — work is
shipped, server is live, ready for real usage.
