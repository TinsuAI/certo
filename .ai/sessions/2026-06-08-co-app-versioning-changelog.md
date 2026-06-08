# Session 2026-06-08 — App versioning + changelog (CO), mirror of Data Hub

## What Was Done

### 1. Session start
- Confirmed CO dev server already running on `127.0.0.1:8001` (PID 1312874,
  `--reload`, HTTP 200) and Data Hub on `:8754`. Reused; no restart.
- Reviewed `.ai/BACKLOG.md`: flagged **D1** (audit delta-vs-full / DH refresh) as
  the highest-risk open item (SAI TỒN); rest is UI/UX (B1-B4) + feedback backlog.

### 2. App versioning + changelog feature (CO `81e2ba5`)
Reciprocal of Data Hub's `feat(versioning)` (`6410329`), per DH brief §10. Read
the full DH implementation and mirrored it ~1:1, adapted to CO.
- **NEW `app/version.py`** — `version_info()`: env (`CO_VERSION/CO_GIT_SHA/
  CO_BUILD_TIME`, build) > pyproject+git (dev) > unknown; `source` field.
- **NEW `app/changelog.py`** — Keep a Changelog line parser, no markdown dep,
  mtime-cached.
- **NEW `CHANGELOG.md`** (root) — curated Vietnamese, 0.1.0..0.13.0 backfilled
  from git history; sections Mới/Cải tiến/Sửa lỗi; user-facing only.
- **NEW `app/templates/whats-new.html`** — extends base.html, CO classes
  (`.zone/.badge/.mono/.meta`), hardcoded Vietnamese (CO has no i18n).
- **`app/routers/pages.py`** — `GET /version` (public JSON, app="barry-co") +
  `GET /whats-new` page.
- **`app/co_auth.py`** — `should_guard_path` += `/whats-new` (auth-gated in prod).
- **`app/web/templating.py` + `app/portfolio.py`** — inject `app_version` into
  BOTH Jinja contexts.
- **`app/templates/base.html`** — footer badge after `</main>`, shown
  unconditionally (works in local no-auth too).
- **`app/static/css/app.css`** — `.app-footer*`, width mirrors `.shell`.
- **Build wiring** — Dockerfile ARG→`CO_*` env + `COPY CHANGELOG.md`;
  docker-compose `build.args`; `ci.yml` exports `CO_VERSION/GIT_SHA/BUILD_TIME`
  before compose build; `pyproject` 0.1.0→0.13.0.
- **Tests** — `test_app_version.py`, `test_changelog_parser.py`,
  `test_whats_new_page.py` (12). Full suite **511 passed / 9 skipped** file-mode.
- Committed `81e2ba5`, pushed `TinsuAI/co main`. CI green (tests 45s, build 17s,
  deploy 1m1s). Prod `/version` → `0.13.0 / 81e2ba5 / source=build`; `/whats-new`
  303→SSO; `/healthz` ok.

### 3. Demo version-bake fix (`tinsu-deploy` `7708d0b`)
- Prod was correct but **demo `/version` = `0.0.0/unknown`** — the nightly
  rebuild is a SEPARATE path (`ci.yml` "Refresh nightly stack" →
  `tinsu-deploy/scripts/rebuild-app.sh co` → `docker-compose.nightly.yml`) that
  passed no build args, so Dockerfile `ARG VERSION=0.0.0` defaults won.
- Edited `TinsuAI/tinsu-deploy` (cloned at `~/workspace/client/tinsu-deploy`):
  `rebuild-app.sh` now exports `${prefix}_VERSION/GIT_SHA/BUILD_TIME` (prefix
  CO|DATA_HUB) from synced `src/$app` before `compose up --build`; `co-app.build`
  switched to args form reading `${CO_VERSION:-0.0.0}`.
- Pushed `7708d0b`; SSH `tinsu` → pull + `rebuild-app.sh co` (logged `baking
  v0.13.0 (81e2ba5)`). Demo `/version` now `0.13.0 / 81e2ba5 / source=build`;
  `/whats-new` 303→SSO. Memory `nightly-demo-version-bake` updated.

## Decisions Made
- **Mirror DH 1:1, adapt to CO.** Env vars `CO_`-prefixed (matches existing
  `CO_AUTH_REQUIRED` etc.); app id `barry-co`; no i18n (hardcode Vietnamese);
  `app_version` (never bare `version`) to avoid colliding with record versioning.
- **`/version` public, `/whats-new` auth-gated.** `/version` mirrors `/healthz`
  (sister apps/monitoring poll it); `/whats-new` added to `should_guard_path` so
  prod requires SSO, but stays open in local no-auth mode.
- **Footer shown unconditionally** (not gated on `co_user`) so the version badge
  is visible in CO's local no-auth dev mode; in prod base.html only renders for
  logged-in users anyway.
- **CHANGELOG copied into the image.** CO Dockerfile only copies
  `app/db/docs/config/assets`; `changelog.py` reads `/app/CHANGELOG.md`, so added
  `COPY CHANGELOG.md ./` — without it the prod page would be empty.
- **Version 0.13.0** — curated backfill of 13 minors telling the product story,
  parallel to DH's 0.13.0.
- **Fixed the demo** (separate infra repo) only after explicit user go-ahead, per
  the "ask before cross-service infra changes" rule. Kept `rebuild-app.sh` change
  generic (per-app prefix) but only wired `co-app` build.args (DH out of scope).

## What Didn't Work / Gotchas
- **First full test run failed** (`test_co_demo.py`): `portfolio.html` extends
  base.html, but the portfolio sub-app has its OWN `Jinja2Templates` +
  `theme_context` that didn't provide `app_version` → `{{ app_version.version }}`
  raised `UndefinedError` (Undefined is falsy for `{% if %}` but attribute access
  raises). Fixed by injecting `app_version` into portfolio's context too — same
  "register on BOTH Jinja envs" lesson as `asset_url` (memory
  `static-asset-cache-busting`).
- **Screenshots not committed:** `.gitignore:26 .ai/features/*/screenshots/`
  ignores them by repo convention (unlike DH). Left local; brief references them.
- **Demo `0.0.0` surprise:** prod and demo are two separate deploy paths;
  prod-only build-wiring changes silently leave the demo stale.
- **zsh:** `ls -t <dir>` and bare globs return wrong output in this shell
  (extended-glob alias). Used `/bin/ls`, `command grep`.

## Open Items
- **DH reciprocal cleanup (optional, needs user OK):** (a) DH demo `/version`
  still `0.0.0` — `dh-app` nightly build needs `build.args` like co-app
  (`rebuild-app.sh` already exports `DATA_HUB_*`); (b) DH prod Dockerfile likely
  missing `COPY CHANGELOG.md` → DH `/whats-new` empty in prod; write a
  sister-app-note for DH.
- **Backlog unchanged:** D1 (delta-vs-full refresh audit, highest risk), Phase 3
  (lot-history noise), UI B1-B4, feedback #14/#13/#4. See `.ai/BACKLOG.md`.
- **Release hygiene:** future version bumps must update both `pyproject.toml` and
  `CHANGELOG.md`; never `[skip ci]` on the deploy tip.
