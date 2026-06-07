# Feature brief — App versioning + changelog on UI (CO)

**Date:** 2026-06-07 (shipped 2026-06-08)
**Status:** Implemented + tested (local). Not yet deployed.
**Origin:** Reciprocal of Data Hub's `feat(versioning)` (`6410329`), per the CO
follow-up in DH's brief §10. Structure mirrors DH ~1:1 (DH descends from CO
templates); adapted to CO's brand (violet `--brand`), auth model, and the fact
that CO has no `app/i18n.py` (Vietnamese copy is hardcoded in templates).

## 1. Goal
Make the running CO release visible/traceable and give every user a "Có gì mới"
changelog page. Before this, the only way to know what's running was the CI
deploy log + `git rev-parse HEAD` on the host.

## 2. Architecture
Four pieces wired by build-arg injection:
1. **Version resolver** `app/version.py` — `version_info()` precedence:
   baked env `CO_VERSION`/`CO_GIT_SHA`/`CO_BUILD_TIME` (build) → pyproject
   version + best-effort `git rev-parse --short HEAD` (dev) → `unknown`.
   `source ∈ {build,dev,unknown}` so the UI shows `(dev)` when unbaked.
   Naming: `CO_`-prefixed + `app_version` in templates, never bare `version`
   (keeps app/release version distinct from BOM/source record versioning).
2. **`/version`** (`app/routers/pages.py`) — unauthenticated like `/healthz`
   (not in `co_auth.should_guard_path`), JSON `{app:"barry-co",version,git_sha,
   build_time,source}`. Sister apps / monitoring can poll which CO they hit.
3. **`CHANGELOG.md`** (root, Keep a Changelog) + parser `app/changelog.py`
   (~70 lines, no markdown dep). Headings `## [x.y.z] — YYYY-MM-DD` (em-dash or
   hyphen) / `## [Unreleased]`; sections **Mới / Cải tiến / Sửa lỗi**; `- `
   bullets. User-facing only — internal refactors/test churn omitted. Cache
   keyed by file mtime.
4. **UI surfaces:**
   - Footer badge on **every** page (`base.html`, after `</main>`): `Barry CO ·
     vX.Y.Z <sha> (dev?)` + "Có gì mới →". Shown unconditionally (not gated on
     `co_user`) so it's visible in CO's local no-auth mode too. `--brand` dot.
   - `/whats-new` page (`whats-new.html` extends `base.html`): running version
     header + each release as a card (version badge + date, sections, bullets),
     newest first. **Auth-gated in prod** (`/whats-new` added to
     `should_guard_path`); open in local/no-auth mode.

## 3. Files touched
| File | Change |
|------|--------|
| `app/version.py` | NEW — resolver + `version_info()` |
| `app/changelog.py` | NEW — `parse_changelog()` / `load_changelog()` |
| `app/routers/pages.py` | `/version` + `/whats-new` routes |
| `app/co_auth.py` | `should_guard_path` += `/whats-new` |
| `app/web/templating.py` | inject `app_version` into `theme_context` |
| `app/portfolio.py` | inject `app_version` into portfolio sub-app context (2nd Jinja env) |
| `app/templates/base.html` | footer version badge |
| `app/templates/whats-new.html` | NEW page |
| `app/static/css/app.css` | `.app-footer*` styles (width mirrors `.shell`) |
| `CHANGELOG.md` | NEW — curated 0.1.0..0.13.0 backfilled from git history |
| `pyproject.toml` | bump 0.1.0 → 0.13.0 |
| `Dockerfile` | build ARGs → `CO_*` env; **`COPY CHANGELOG.md ./`** |
| `docker-compose.yml` | `build.args` VERSION/GIT_SHA/BUILD_TIME |
| `.github/workflows/ci.yml` | export `CO_VERSION/GIT_SHA/BUILD_TIME` before compose build |
| `tests/test_app_version.py`, `tests/test_changelog_parser.py`, `tests/test_whats_new_page.py` | NEW — 12 tests |

## 4. Notable divergences from DH
- **Two Jinja envs.** CO's portfolio sub-app (`app/portfolio.py`) has its own
  `Jinja2Templates` + `theme_context`. `base.html`'s `{{ app_version.version }}`
  raises `UndefinedError` there unless app_version is injected into BOTH envs
  (same gotcha as `asset_url` — memory `static-asset-cache-busting`). Fixed.
- **CHANGELOG copied into the image.** CO's Dockerfile only copies
  `app/db/docs/config/assets`; `app/changelog.py` reads `parent.parent/
  CHANGELOG.md` = `/app/CHANGELOG.md`, so without `COPY CHANGELOG.md ./` the
  prod page would be empty. Added. **DH's Dockerfile appears NOT to copy
  CHANGELOG.md** → DH's `/whats-new` may render empty in prod (flag to DH).
- **No i18n.** DH used `t('nav.whats_new')`; CO hardcodes Vietnamese.
- **Auth.** DH has a local `/login` form; CO is DH SSO. The auth-gate test sets
  `CO_AUTH_REQUIRED=1` and asserts the 303 → `/auth/login?next=/whats-new`.

## 5. Verification
- `uv run pytest -q` (file-mode, no .env): **511 passed, 9 skipped**.
- Live dev (`:8001`): `/version` → `{"app":"barry-co","version":"0.13.0",
  "git_sha":"0bbebda","build_time":"dev","source":"dev"}`; `/whats-new` → 200
  with running version + changelog; footer on `/clients`.
- Screenshots (light/dark footer + whats-new) in `screenshots/`.

## 6. Release process (going forward)
Per release: (1) bump `pyproject.toml` version, (2) add a dated `## [x.y.z]`
section to `CHANGELOG.md` (Mới/Cải tiến/Sửa lỗi), (3) commit, (4) push
`TinsuAI/co main` → CI bakes `CO_VERSION/GIT_SHA/BUILD_TIME` and auto-deploys.

## 7. Deferred / out of scope
- "Unseen version" dot on the footer (cookie last-seen) — DH brief §4.3, skipped.
- Cross-app status panel showing the other app's `/version` — both now expose
  `/version`, so a future integration panel can poll it.
- GHCR image tags — unchanged (single deploy host, build-on-host with baked args).
