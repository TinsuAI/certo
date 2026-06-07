# Project Status

## Current State
- **CO-stock detangle Phase 3 — lot-history modal fold — MERGED + DEPLOYED
  (prod + demo, 2026-06-08, HEAD `7a68570`).** Display-only cleanup of the
  per-lot "Lịch sử" modal: chốt→mở-chốt→chốt writes both `claim_lock` +
  `claim_release`; ledger dedup only skips re-locks while the sheet is still
  locked, so post-unlock churn accumulated → noisy modal. Tồn never wrong
  (remaining sums only `locked`). Ledger + `co_stock_events` rows UNTOUCHED.
  - **`fold_lot_events()`** (pure, `co_stock_events_store.py`): collapse a
    lot's raw events into one net row per `(case_id, sheet)` claim stream —
    holding (net<0) / released (net=0) / anomaly (net>0); manual adjustments
    pass through as singletons. Sign matches emission (`claim_lock` qty>0
    effect−, all `claim_release` qty<0 effect+).
  - **`/lot-history`** returns `groups` alongside raw `events`. **Modal**
    (`co_stock.html`) defaults to folded view; **"Chi tiết"** toggle restores
    raw log (SAU running-balance walk unchanged); header labels swap per mode.
  - **Verified:** 10 new unit tests (`tests/test_co_stock_lot_history_fold.py`);
    file-mode suite **521 passed / 9 skipped**; Playwright stub-fetch confirms
    grouped (6 events→3 rows) + detail toggle render. CI green; prod+demo
    `/version` → `0.13.0 / 7a68570 / source=build` (display-only, no version bump).
  - **OUT of scope (deferred):** R1/R2/R3 (delete-case audit) are data/schema
    — snapshot case identity onto release event (GAP A `case <id>` still raw),
    soft-delete/tombstone, `case_delete` event. Discovery in
    `.ai/audits/2026-06-07-delete-case-stock-history-audit.md`.
- **App versioning + changelog — MERGED to `main` + DEPLOYED (prod + demo,
  2026-06-08).** Mirror of Data Hub's `feat(versioning)`. CO `main` HEAD
  `81e2ba5`; demo fixed via `TinsuAI/tinsu-deploy` `7708d0b`. Both stacks
  verified.
  - **Surfaces:** footer version badge on every page (`base.html`, violet
    `--brand` dot, `Barry CO · vX.Y.Z <sha> (dev?)` + "Có gì mới →");
    `/whats-new` changelog page (auth-gated in prod via `should_guard_path`,
    open in local no-auth); `GET /version` unauthenticated like `/healthz`
    (`{app:"barry-co",version,git_sha,build_time,source}`).
  - **Resolver `app/version.py`:** env (`CO_VERSION/CO_GIT_SHA/CO_BUILD_TIME`,
    build) > pyproject+git (dev) > unknown; `source` ∈ build|dev|unknown.
  - **Changelog `app/changelog.py`:** Keep a Changelog parser, no markdown dep;
    curated `CHANGELOG.md` (root, Vietnamese, 0.1.0..0.13.0, Mới/Cải tiến/Sửa lỗi).
  - **Build wiring:** Dockerfile ARG→`CO_*` env + `COPY CHANGELOG.md`; compose
    `build.args`; CI bakes `CO_VERSION/GIT_SHA/BUILD_TIME` before compose build;
    `pyproject` 0.1.0→0.13.0.
  - **Two Jinja envs:** `app_version` injected into BOTH `app/web/templating.py`
    `theme_context` AND `app/portfolio.py` (sub-app), else `{{ app_version.version }}`
    raises `UndefinedError` in portfolio (same gotcha as `asset_url`).
  - **Verified:** file-mode tests **511 passed / 9 skipped** (12 new); CI green;
    prod+demo `/version` → `0.13.0 / 81e2ba5 / source=build`; `/whats-new` 303→SSO.
  - Brief `.ai/features/2026-06-07-co-app-versioning-changelog/brief.md`
    (folder dated 06-07; work spanned into 06-08). Screenshots local-only
    (`.gitignore:26 .ai/features/*/screenshots/`).
- **Deployed baseline (prod `barry-co.tinsu.ai` :8755 + demo `demo-co.tinsu.ai`
  :8765, all on `main`):** CO-stock detangle Phase 1+2 + refresh fix (`11dbff8`),
  app-identity brand chrome (`1f2b6dd`), CO-case list redesign (`ee70a4b`), UX
  Primer redesign (`a33eaae`), background dossier export (`dc1b582`), merged
  TKX/TKN PDF dossier, content-hash static cache-busting, CO→DH operator-JWT
  auth, #12 số tồn tổng. CI green, nightly refreshed.

## Recent Changes (latest first)
- **CO-stock Phase 3 — lot-history modal fold** (`7a68570`, 2026-06-08): see
  Current State. +new `tests/test_co_stock_lot_history_fold.py`; edits to
  `co_stock_events_store.py` (`fold_lot_events`), `routers/co_stock.py`,
  `templates/co_stock.html`, `static/css/app.css`.
- **App versioning + changelog** (`81e2ba5`, 2026-06-08): see Current State.
  +new `app/version.py`, `app/changelog.py`, `CHANGELOG.md`,
  `app/templates/whats-new.html`, 3 test files; edits to `pages.py`, `co_auth.py`,
  `templating.py`, `portfolio.py`, `base.html`, `app.css`, Dockerfile,
  docker-compose, `ci.yml`, `pyproject.toml`.
- **Demo version-bake fix** (`tinsu-deploy` `7708d0b`, 2026-06-08): nightly
  rebuild path (`scripts/rebuild-app.sh` + `docker-compose.nightly.yml co-app`)
  now bakes `CO_VERSION/GIT_SHA/BUILD_TIME`. Was showing `0.0.0/unknown` because
  the nightly path is SEPARATE from prod CI and passed no build args.

## Next Steps (priority order)
1. **(Optional) DH-side reciprocal cleanup** (raised this session, not done —
   needs user go-ahead, touches DH/tinsu-deploy):
   - DH demo `/version` still `0.0.0`: `rebuild-app.sh` now exports `DATA_HUB_*`
     but `dh-app` nightly build is still short `build: ./src/data-hub` (no
     `build.args`) — wire it like co-app.
   - DH prod Dockerfile likely missing `COPY CHANGELOG.md` → DH `/whats-new`
     empty in prod. Write a sister-app-note for DH.
2. **BACKLOG D1 — audit delta-vs-full / Data Hub refresh thoroughly.** Empty-
   snapshot strand (`039baeb`) was one symptom; audit whole refresh_state ↔
   co_stock_rows desync + delta/full parity. `/discover` + parity tests first.
   Highest-risk open item (SAI TỒN). See `.ai/BACKLOG.md` D1.
3. ~~**Phase 3 — clean Tồn CO lot-history noise**~~ ✅ DONE (`7a68570`,
   2026-06-08, deployed). Modal folds chốt/mở-chốt churn into net rows +
   "Chi tiết" toggle. Remaining: delete-case audit R1/R2/R3 (data/schema —
   case identity snapshot, soft-delete, `case_delete` event) — still open.
4. **UI backlog (`.ai/BACKLOG.md`):** B1 "Đổi công ty/hồ sơ" → modal; B2 workflow
   step-status display; B3 bảng kê column layout; B4 full-width case UI.
5. Feedback backlog: #14 (BOM default per code), #13 (batch chốt BOM), #4 (DH
   substitute ranking via api-request).

## Notes for Next AI Session
- **Branch state:** CO on `main`, HEAD `7a68570` = deployed (Phase 3). tinsu-deploy
  on `main`, clean, HEAD `7708d0b` = deployed. Local clones:
  `~/workspace/client/{barry-CO-main, data-hub, tinsu-deploy}`.
- **Release process going forward:** per release (1) bump `pyproject.toml`
  version, (2) add a dated `## [x.y.z]` section to `CHANGELOG.md`
  (Mới/Cải tiến/Sửa lỗi, user-facing only), (3) commit, (4) push `TinsuAI/co main`
  → CI bakes version + auto-deploys. NO `[skip ci]` on the tip or the deploy is
  skipped (re-trigger `gh workflow run ci.yml --ref main`).
- **Two deploy paths (memory `nightly-demo-version-bake`):** prod = CO `ci.yml`
  "Deploy on tinsu"; demo = `ci.yml` "Refresh nightly stack" →
  `tinsu-deploy/scripts/rebuild-app.sh co`. Changes to prod build wiring do NOT
  reach the demo automatically — they live in the separate `TinsuAI/tinsu-deploy`
  repo. Demo redeploy: SSH `tinsu` → `cd /home/tinsu/tinsu-deploy && git pull
  --ff-only && scripts/rebuild-app.sh co`.
- **Local dev:** `npm run co:serve` → `127.0.0.1:8001` (auth off, `--reload`
  watching `app/**` *.py/*.html/*.css). Server was already running this session.
  PG `barry_co` via unix socket (`.env BARRY_DATABASE_URL`).
- **Tests:** `uv run pytest` file-mode (no .env) = 511 passed. DB-backed tests
  need `.env` sourced (memory `test-env-filemode-vs-datahub`).
- **zsh gotcha:** `ls -t <dir>`/bare globs misbehave in this shell (extended-glob
  alias) — use `/bin/ls` and `command grep`; quote grep `--include="*.py"`.
