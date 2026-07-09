# 2026-07-10 — CO session died every ~10 min: XHR 401 fix + DH refresh-token consumer

Diagnosed a prod-only user-reported bug (Johnson VN: "Tìm NVL thay thế" lost
connection every ~10 minutes with `TypeError: Failed to fetch`, discarding all
client-side substitute work), shipped a two-tier fix, merged to `main`, deployed.
Full arc: `/diagnosing-bugs` → 2-tier fix (TDD) → live + browser verify → PR #4 →
CI green → merge `origin/main`=`306e2b4` → `Deploy demo` SUCCESS.

## Root cause
The CO session is the Data Hub access token stored in the `co_data_hub_session`
cookie. It is minted **once** at the SSO callback with `max_age = expires_in or
600` (`co_auth.set_session_cookie`, `routers/auth.py:auth_callback`) and the DH
JWT `exp` is the same ~600s — **confirmed `expires_in=600` against the live DH**,
so "~10 minutes" was literal, not a user's feeling. There is **no sliding refresh
and no refresh-token renewal**. On expiry the next guarded `/clients/...` fetch
hits `guard_response` → `login_redirect` → **303 → `/auth/login` → 303 →
`{data_hub}/v1/auth/authorize` (cross-origin)**. `fetch()` follows the redirect;
the SSO page returns no CORS headers → the browser aborts with `TypeError: Failed
to fetch`. `base.html`'s wrapper surfaced it as the promise-reject toast ("Mất kết
nối máy chủ") + the recommendation catch ("Lỗi tải khuyến nghị"). **Prod-only**
because dev runs `CO_AUTH_REQUIRED=0` → `guard_response` returns early → no
redirect. Work was lost because recovery meant a full SSO page reload.

The decisive discriminator: the screenshot showed the *promise-reject* toast, not
the *HTTP-error* toast ("Lỗi máy chủ HTTP …") — that rules out OOM / worker crash
/ payload-limit / DH-500 (all return a readable status) and points squarely at a
cross-origin redirect abort.

## What was done
1. **Phase-1 feedback loop (red-capable):** `tests/test_session_expiry_xhr_guard.py`
   — with `CO_AUTH_REQUIRED=1` + expired/absent cookie, a guarded API request
   returns 303 (bug) instead of a readable 401. 1.7s, deterministic, red.
2. **Tier 1 — CO-side resilience (`84182cd`):**
   - `co_auth.is_xhr_request()` + `auth_challenge()`: guarded requests that
     announce themselves as fetch/XHR (`Sec-Fetch-Dest`≠document / `X-Requested-With`
     / JSON-only `Accept`) get **`401 {code:"session_expired", login_url}`**;
     document navigations keep the SSO 303.
   - `base.html` fetch-wrapper: on 401 `session_expired` shows a re-login overlay
     (`coSessionExpired`, reuses `.modal-backdrop`/`.confirm-modal`) that opens
     SSO **in a new tab** so the page + in-progress work survive.
3. **DH contract artifacts (`c8a5316`):** `.ai/api-requests/2026-07-10-session-
   token-refresh.md` (template contract) + `-dh-prompt.md` (self-contained,
   paste-ready DH build prompt). **On testing, DH had already implemented it** —
   rotating `refresh_token` at `/v1/auth/exchange` + `POST /v1/auth/refresh`
   (sliding idle-TTL, 7-day absolute ceiling, rotation reuse-detection, claims
   rebuilt live and never broadened) — see DH `app/routes/auth_api.py` +
   `app/stores/sso_refresh.py`.
4. **Tier 2 — CO consumer (`8797d16`):** `co_auth.refresh_data_hub_session()` →
   `POST {api}/v1/auth/refresh`; `co_data_hub_refresh` cookie; `clear_session_cookie`
   drops both; `routers/auth.py` stores the refresh cookie at callback + adds
   `POST /auth/refresh` (rotates both cookies; on any DH rejection clears cookies +
   `session_expired`). `base.html` wrapper upgraded to **silently refresh on a 401
   then transparently replay idempotent (GET) requests**; non-GET prompts a redo.
   Tests: `tests/test_session_refresh_consumer.py`.
5. **Verification (heavy, mostly no mocks).** ⚠ Scope note: every "real DH" test
   below ran against a **LOCAL Data Hub instance** (`127.0.0.1:8754`) — same code
   as the deployed DH, but a **different instance**. The deployed stack shares one
   DH (`data-hub-app-1`) between prod `co-app-1` and nightly `nightly-co-app-1`.
   - Full suite **760 pass / 10 skip** (+9 new).
   - Local DH probes: `/v1/auth/refresh` empty→400, bogus/JWT-shaped→401.
   - CO↔DH **real** round-trip (local DH): negative (bad refresh cookie → DH → 401 →
     session_expired + clears cookies); positive via **scripted SSO** (httpx drives
     DH's CSRF-free `/login` form → authorize → exchange → real refresh token →
     CO `/auth/refresh` → 200, rotates cookies; refreshed token verified valid via
     `GET /user` 200 against real JWKS). Also proved DH rotation reuse-detection
     (spent token → 401).
   - **Browser E2E** (puppeteer, real Chrome, auth-on CO `:8011` → local DH): SSO
     login → both cookies set; delete session cookie (simulate expiry) → next XHR
     → **silent `/auth/refresh` + replay → 200, no prompt, session restored**;
     delete both cookies → XHR → **graceful re-login overlay** (not "Failed to fetch").
   - **Deployed smoke** (unauthenticated, read-only) on **prod `barry-co.tinsu.ai`
     AND nightly `demo-co.tinsu.ai`, both `git_sha=306e2b4`**: `GET /version` 200;
     **XHR guarded + no session → `401 {code:session_expired}`** (the root cause,
     confirmed fixed *on prod*); NAV guarded → `303 → /auth/login` (preserved);
     `POST /auth/refresh` no cookie → 401 `session_expired` (new route live).
6. **Ship:** branch `fix/session-expiry-xhr-401` → PR #4 → CI (tests+docker green,
   deploy skipped on PR) → merged `origin/main`=`306e2b4` → main run `29035894495`
   `Deploy demo` SUCCESS.

## Decisions (user-made)
- **Do both tiers** — CO-side resilience now + pursue the DH refresh root fix.
- **Build the repro test first** (red→green) before touching auth.
- **Commit / push / PR / merge / deploy** each explicitly authorized in sequence.
- (Engineering) **XHR detection is positive** — only requests that clearly announce
  themselves divert to JSON 401; a bare navigation still gets the redirect.

## What didn't work / gotchas
- **First XHR heuristic (default = XHR, redirect only if `text/html` in Accept)
  broke 4 existing tests** that simulate a nav with a bare `TestClient.get` (Accept
  `*/*`, no Sec-Fetch). Flipped to positive detection → existing behaviour preserved.
- **CO had no consumer built** — only the api-request artifact existed; "test the
  flow" required building the CO half first (DH was already done).
- **A real refresh token needs the SSO browser flow** — DH `/v1/auth/token`
  (password) returns no refresh token (only `/exchange` binds one to an SSO
  session). Scripted DH's `/login` (plain form POST, **no CSRF**) with httpx to get
  a real token for the server round-trip; browser E2E for the client JS.
- **`git push` blocked by the project git-guardrails hook** (`.claude/hooks/
  block-dangerous-git.sh`, matches `git push` for any branch) → user ran it via `!`.
  `gh pr merge` is **not** blocked (merged to main → triggered prod CD as intended).
- **puppeteer `require` failed from the scratchpad dir** → `NODE_PATH=$(pwd)/node_modules`.
- zsh no-glob on `grep --include=*.py` → quote the pattern.
- Local dev `/` and `/clients` return **503** here (source backend not provisioned
  in this env) — unrelated to the change; `/whats-new`, `/user`, `/settings/technical`
  render fine and served the new JS.

## Open items
- **GIT: `local main` (= this docs commit) is AHEAD of `origin/main`=`306e2b4`
  by 1, UNPUSHED.** Pushing `main` is blocked by the project git-guardrails hook →
  user's manual step (`!git push origin main`); docs-only, so CI just re-runs
  `Deploy demo` with no app change. Merged branch `fix/session-expiry-xhr-401` still
  exists local + remote (not deleted).
- **Deployed AUTHENTICATED refresh path NOT verified.** The guard fix and
  `/auth/refresh` existence + failure path are confirmed on prod and nightly (see
  Verification), but the **success** path (valid refresh token → 200 + rotation) was
  never exercised on the deployed stack: minting a credential inside `data-hub-app-1`
  (create SSO session + `sso_refresh.issue`) was **denied by the permission
  classifier**. Read-only DB queries were allowed (user list). Three ways forward:
  (a) grant a Bash permission rule, then mint for the automation account
  `claude-check-temp` and test against nightly; (b) log into `demo-co` manually and
  hand over the `co_data_hub_refresh` cookie (single-use — it rotates on first use,
  so it will kick that browser session); (c) accept current coverage — identical code
  (`306e2b4`) proven against a local DH instance + a real browser.
- **Enhancements NOT built** (reactive retry-on-401 is the shipped, sufficient
  mechanism): (a) proactive keep-alive timer that refreshes before expiry (avoids the
  one-request latency); (b) auto-close the re-login tab + auto-retry after callback;
  (c) server-side autosave of the substitute plan for durability across a *manual*
  page reload (client-only state still dies if the user reloads).
- **Real-user soak still pending** — prod (`barry-co`) and nightly (`demo-co`) are both
  confirmed on `306e2b4`, so no separate prod deploy is needed. What remains is a real
  Johnson VN operator working past ~10 min and confirming no disconnect / no lost
  substitute plan.
- **DH api-request "Approval" section is blank** — DH already implemented; backfill
  owner / commit if that record matters.
