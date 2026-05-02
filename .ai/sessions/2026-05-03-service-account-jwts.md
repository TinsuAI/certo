# Session: 2026-05-03 — Service-account JWTs + housekeeping

Two distinct chunks of work:
1. Service-account JWTs (the planned big item) — full /discover → TDD → /rev → commit cycle.
2. Housekeeping — STATUS/BACKLOG refresh, dev port pin, CO sister-app status check, data/ structure review, screenshots untrack.

## What Was Done

### Discovery: assumed work plan, found half already shipped (commit 9689210)

Started from STATUS.md "Next Steps" + a memory of the BACKLOG. Proposed a 6-item plan: STATUS refresh, port pin, Bug C fix, Bug A fix, Bug B alias, CO nudge, confirm-gate to 4 modules, staleness banner, catalog provenance, JWTs.

Verification round (`git log --all` + reading actual code) revealed 8 of those 13 tasks were ALREADY shipped in HEAD:
- Bugs A/B/C — fixed in `338be91` Phase 1
- Confirm-gate to all 4 modules — `359ebec` Phase 2 universal preview
- Staleness banner — `53da49b` A3 (all 4 tabs, not just BCCT)
- Catalog multi-source provenance — `6141d1e` A4

STATUS.md "Current State" paragraph was actually accurate; only "Recent Changes" was anchored to Hướng B (the most recent sprint). The mistake was trusting a stale memory of BACKLOG over reading the code first. Saved as memory `feedback_verify_status_vs_code.md` for future sessions.

Real remaining work after that audit: STATUS refresh, AGENTS port pin, BACKLOG cleanup, CO nudge, service-account JWTs.

### Service-account JWTs (commit a47df52)

Full risky-change protocol per AGENTS.md.

**Discovery doc:** `.ai/features/2026-05-02-service-account-jwts.md` — design + scope + tests required + risk + done criteria. Out-of-scope: admin UI (CLI is enough for ~2 SAs), audit GUC integration for service writes (no current write path uses it), OAuth refresh tokens (just re-mint on TTL).

**Schema (migration 020):**
- `hub.service_accounts(name PK, description, scopes[], client_ids?[], created_by, last_used_at)` — soft revoke = delete row.
- `hub.revoked_service_tokens(jti PK, ...)` — fast emergency revocation between mint and natural expiry.
- `app_settings.service_token_ttl_seconds = 2_592_000` (30d default).

**Token shape:** `typ=service` claim, `sub=svc:<name>`, 30d default TTL, jti UUID4. Same Ed25519 signing key + JWKS as user tokens — consumers verify identically; only claim shape differs.

**Code:**
- `app/stores/service_accounts.py` — CRUD + jti blacklist
- `app/jwt_issuer.py:make_service_token` + `_validate_service_token` (re-derives scopes + client_ids from registry on every verify)
- `app/jwt_issuer.py:ServiceTokenInvalid` — distinct exception subclass
- `app/routes/api.py` — `_is_service_claims`, `_require_scope`, ACL branching in view/edit helpers
- `scripts/mint_service_token.py` — CLI: create, list, delete, revoke-jti
- 20 tests in `tests/test_service_account_jwts.py`

**Per-endpoint scope mapping:**
- All `GET /v1/hub/*` → require `hub:read`
- `POST /v1/hub/products/{code}/bom/proposals` → require `bom:propose`

**Self-/rev pass caught 4 critical issues, all fixed BEFORE commit:**

- **C1 — sub/name mismatch.** Token could claim `sub=svc:bcqt, name=co` and inherit CO's registry row while audit shows bcqt. Fix: assert `sub == f"svc:{name}"`. Plus re-derive scopes + client_ids from registry instead of trusting JWT body — admin updates take effect immediately, not after 30d expiry.
- **C2 — scopes type confusion.** `_require_scope` did `scope in claims["scopes"]`; if claims had `scopes="hub:read,bom:propose"` (string instead of list), substring match would pass. Fix: `isinstance(granted, list)` check.
- **C3 — auth bypass in non-strict mode.** `_validate_service_token` raised generic `InvalidTokenError`, which `_require_token` caught and treated as "permissive bearer fallback" → returned `None` → unauthenticated god mode. A revoked service token in dev mode = full access. Fix: `ServiceTokenInvalid` subclass, caught BEFORE the strict-mode branch, always 401.
- **I1 — CLI footgun.** `--client-ids ""` (empty string) was falsy → `client_ids=None` → "all clients" instead of intended "no clients". Fix: explicit empty-string rejection + `_NAME_RE` validation (`^[a-z][a-z0-9_-]{0,31}$`).

7 regression tests pin each of these.

**Sister-app coordination:** `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md` written for CO + BCQT (consumer-side verifier instructions, mint commands, refresh-flow absence). Then deferred adoption to BACKLOG per user request — coexistence works fine, no urgency until `api_auth_strict=true` flip (commit 77314be).

### Manual test (in-session, not committed)

Walked the full surface end-to-end via curl + CLI. 10 cases all PASS:
- CLI create → list (last_used=never) → API call → list (last_used=timestamp): bump verified.
- Whitelist allow (growatt-vn) vs deny (johnson-vn).
- Scope deny: `hub:read`-only token POST proposal → 403 missing scope.
- Scope allow: `bom:propose` token POST proposal → 400 business validation (NOT scope error).
- JTI revoke: token before=200, after=401 "service token revoked".
- **C3 regression:** soft revoke (delete account) in non-strict mode (`api_auth_strict=false`) → token rejects with 401, NOT permissive 200.

### Demo confirm-gate UX (commit d7ae89d adds the script)

User asked to see preview-confirm pattern beyond just BCCT. Wrote `scripts/demo_confirm_gate.py` (Playwright) — drives one upload per module, captures preview screenshot, rejects to keep DB clean. For BCCT also runs the DIFF/ORPHAN scenario (upload baseline 03a confirm, then 03b which changes 1 + removes 1 + adds 1).

5 screenshots captured at `data/screenshots/confirm_gate_demo/`. Showed user 5 inline; key observations:
- Tone differs by risk: all-NEW = "Xem trước trước khi lưu"; DIFF/ORPHAN = "Xác nhận thay đổi" (heading nhấn mạnh).
- Per-module summary panels are domain-specific (BQD shows 1-N count, Catalog shows category × status, BOM groups by product).
- BOM/BQD/Catalog use 3-button form via `formaction=`; BCCT uses single-button `<form action=...>`. Two patterns from different build phases.
- Pending ID + expires-at shown on page (24h TTL).

### Housekeeping

**`fix(test): _cleanup.sql` (commit adb7aa2):** Bug found while running cleanup after demo. `materials.product_code` was renamed to `internal_code` in commit `b2642d6` but `_cleanup.sql` wasn't updated. Failed silently (DELETE 0 for materials), leaving MAN_* rows.

**`data/` structure review:** User asked "what's in data/?". Audit found:
- `data/seeds/` (12K, tracked) — first-install YAML; correct.
- `data/files/` (34M, gitignored) — uploaded artifact storage; correct (env override `DATA_HUB_FILES_DIR=/var/lib/data-hub/files` for prod).
- `data/manual_test/` (144K, tracked) — XLSX fixtures + cleanup SQL; correct.
- `data/screenshots/` (39M, mostly tracked) — **problem**. 67 files, 37.4MB. All script-generated (`screenshot.py`, `smoke_real_uploads.py`, my new `demo_confirm_gate.py`). Top 10 history blobs ALL screenshots, totaling >50MB lifetime. No visual regression code consumes them. Stale-by-default since `screenshot.py` covers only 27 basic CRUD pages (missed admin, declaration-config, preview, parse-mapping, history, chat widget, notifications).

User chose option A (gitignore all data/screenshots/, untrack from index, don't restructure data/ otherwise). Commits d7ae89d (gitignore + README + demo script) + 18f29e2 (the actual `git rm --cached` — split into separate commit because a stray `git reset HEAD` undid the unstage between rm and commit).

## Decisions Made

- **STATUS.md is reasonably accurate; just refresh the prior-cycles pointer.** Initially proposed full STATUS rewrite; on closer reading the "Current State" paragraph already reflects HEAD. Only added a "Prior cycles" section pointing to session summaries + commit ranges. Less surgery, less risk of introducing drift.
- **Service-account JWTs: authorization from DB, not token.** Original BACKLOG sketch had token carry scopes/client_ids. /rev caught that this means admin can't shrink permissions until 30d TTL. Re-derive on every verify — small DB hit, big correctness win.
- **`ServiceTokenInvalid` distinct exception, not generic `InvalidTokenError`.** Required to prevent permissive-bearer fallback in dev mode from accepting revoked service tokens. Sub-classed `jwt.InvalidTokenError` so existing exception-handling code still works as a baseline.
- **CLI script, no admin UI for v1.** Volume tiny (~2 SAs); ops handles re-mint manually on TTL. Don't build a refresh-token endpoint that doesn't have a UI consumer.
- **30d TTL default.** Long enough that operator re-mint isn't constant pain; short enough that a leaked token has bounded blast radius. jti blacklist for emergency revoke between mint and expiry.
- **Defer CO/BCQT adoption to BACKLOG.** User said "overload" after seeing the 3-step adoption guide. Coexistence with permissive bearer / user JWT works fine; not urgent until `api_auth_strict=true` flip. Removed from STATUS Next Steps.
- **`data/screenshots/` gitignore: option A (all gitignored), not option B (commit as visual baseline).** No comparison code exists; committing without comparison is dead asset. Pre-MVP scaffold = good moment to set the pattern before sister-app patterns crystallize.
- **3 commits for the screenshot cleanup, not 2.** Stray `git reset HEAD` undid an earlier `git rm --cached`; followed AGENTS.md rule "create NEW commits rather than amending" and added a 3rd commit explaining what happened.

## What Didn't Work

- **Initial work plan based on STATUS.md "Next Steps" was 50% wrong** — half the items were already shipped in HEAD. STATUS.md was reasonable but my memory of BACKLOG was stale. Lesson saved to memory.
- **First Playwright login attempt** in `demo_confirm_gate.py` waited for `/` redirect; actual login goes to `/clients`. Fixed.
- **First `git add data/screenshots/` after gitignore** failed (the path was now gitignored). Had to use `git rm --cached -r` for index removal; gitignore + add only blocks NEW additions.
- **Test 5 in manual walkthrough first attempt** captured an empty token because `2>/dev/null` swallowed the "account already exists" error and `tail -1` got an empty line. Worked once I added `delete --name ro_test` first.
- **Screenshot naming pattern misled me into proposing `docs/screenshots/`.** User correctly pushed back — numbered files looked curated but were actually just script output. Reframed to gitignore all.

## Open Items

- **CO migration cutover by 2026-05-16** — verified NOT STARTED 2026-05-02. 13 days remaining as of 2026-05-03.
- **Service-account JWT adoption (CO + BCQT)** — sitting in BACKLOG. Becomes ship-blocking when ready to flip `api_auth_strict=true`.
- **`screenshot.py` coverage gap** — covers 27 basic CRUD pages, missed all 2026-05-02 sprint additions (admin/*, declaration-config, preview, parse-mapping, history, chat widget, notifications). Worth extending if anyone uses screenshots for design review; not urgent for code health.
- **Dev server still running** at `:8754` from this session.

## Files Touched

**Created:**
- `db/migrations/020_service_accounts.sql`
- `app/stores/service_accounts.py`
- `scripts/mint_service_token.py`
- `scripts/demo_confirm_gate.py`
- `tests/test_service_account_jwts.py`
- `.ai/features/2026-05-02-service-account-jwts.md`
- `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`

**Modified:**
- `app/jwt_issuer.py` (+97 lines: `make_service_token`, `_validate_service_token`, `ServiceTokenInvalid`)
- `app/routes/api.py` (+57 lines: scope param, service-claims branching)
- `.ai/STATUS.md` (refresh + prior-cycles section)
- `.ai/BACKLOG.md` (-186 lines: trim shipped + add SA adoption entry)
- `.ai/sister-app-notes/2026-05-02-co-migrate-to-client-config.md` (+22 lines: status check)
- `AGENTS.md` (+14 lines: Build & Run + dev port pin)
- `data/manual_test/_cleanup.sql` (1-line column rename)
- `README.md` (1-line gitignore note)
- `.gitignore` (+1: `data/screenshots/`)

**Untracked from index** (files preserved on disk):
- 67 files in `data/screenshots/` (~37MB)
