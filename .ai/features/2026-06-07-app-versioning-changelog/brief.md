# Feature brief — App versioning + changelog on UI

**Date:** 2026-06-07
**Status:** Research / design (no implementation yet)
**Scope:** Data Hub now. CO gets a reciprocal outbound prompt after DH ships (see §10).

## 1. Goal

Make the **running app's release version** visible and traceable, and give
every logged-in user a **"Có gì mới" (What's new) changelog** page. Today
the only way to know "what's running" is the CI deploy log +
`git rev-parse HEAD` on the host. `docs/release-engineering.md` already
lists the `/version` endpoint as an unstarted **open item**; this feature
closes it and adds the UI surface.

### Decisions locked (with user, 2026-06-07)
- **Kind:** app/release version (semver + git SHA), NOT data-record
  versioning. (BOM artifacts / `declaration.config_version` already cover
  record versioning — out of scope here.)
- **Changelog source:** curated `CHANGELOG.md` (Keep a Changelog format),
  rendered to a UI page. Vietnamese, user-facing copy.
- **Audience:** all logged-in users see the "Có gì mới" page + a version
  badge in the footer.

## 2. Current state (verified against HEAD `55385b2`)

| Thing | State |
|-------|-------|
| `pyproject.toml` version | `0.1.0`, never bumped |
| git tags | none |
| `/version` endpoint | not implemented (open item in release-eng doc) |
| Version in UI | none; `base.html` has no footer |
| Dockerfile build args | none — image carries no version metadata |
| CI build | `docker compose up -d --build` on host after `git reset --hard origin/main`; no version injected |
| Markdown renderer | no dep (`markdown`/`mistune` absent); `app/llm.py` is the only `markdown` mention |
| i18n | `app/i18n.py` — `STRINGS["vi"|"en"]` dict + `t(key, lang)`; add keys there |
| `/healthz` | trivial `{"status":"ok"}` at `app/main.py:195` — model `/version` next to it |

## 3. Architecture

Four pieces: **version resolver** → **`/version` endpoint** → **curated
`CHANGELOG.md` + parser** → **UI surfaces (footer badge + What's-new page)**,
wired by **build-arg injection** in Dockerfile/compose/CI.

### 3.1 Version resolver — `app/version.py`

Single module that resolves version info with precedence:

1. **Baked env** (set at build): `DATA_HUB_VERSION`, `DATA_HUB_GIT_SHA`,
   `DATA_HUB_BUILD_TIME`. Authoritative in any built image.
2. **Dev fallback**: read `version` from `pyproject.toml` + best-effort
   `git rev-parse --short HEAD` (wrapped in try/except — no git in image,
   and we don't want a hard dep at runtime).
3. **`"unknown"`** if both fail.

Exposes a cached `version_info() -> {version, git_sha, build_time, source}`
where `source ∈ {"build","dev","unknown"}` (so the UI can show "(dev)" when
running unbaked). Cache at module load — version never changes within a
process.

> Naming note (per `feedback_naming_discipline`): use `app_version` /
> `DATA_HUB_VERSION`, never bare `version`, to avoid colliding with
> `declaration.config_version` and BOM artifact versioning.

### 3.2 `/version` endpoint

`GET /version` — **unauthenticated** like `/healthz` (it leaks nothing
sensitive; sister apps + monitoring poll it). Returns:

```json
{ "app": "data-hub", "version": "0.2.0", "git_sha": "a1b2c3d",
  "build_time": "2026-06-07T14:30:00Z", "source": "build" }
```

Closes the release-eng open item. BCQT/CO can poll it to assert which DH
they're talking to.

### 3.3 `CHANGELOG.md` (curated, Keep a Changelog)

Root `CHANGELOG.md`. Structure constrained so a tiny in-house parser
suffices (no new dep):

```markdown
# Changelog

## [0.2.0] — 2026-06-07
### Mới
- Trang "Có gì mới" và hiển thị phiên bản ứng dụng.
### Cải tiến
- Giao diện đồng bộ với hệ thiết kế Primer.
### Sửa lỗi
- ...

## [0.1.0] — 2026-04-30
### Mới
- Bản scaffold đầu tiên.
```

- Headings: `## [x.y.z] — YYYY-MM-DD` (+ optional `## [Unreleased]`).
- Section headings (Vietnamese, user-facing): **Mới / Cải tiến / Sửa lỗi**
  (map of Keep-a-Changelog Added/Changed/Fixed). Internal-only churn
  (refactors, test plumbing) is deliberately **omitted** — this is a
  user-facing changelog, not a commit dump.
- Bullets only under sections. No nested markdown beyond `- `.

### 3.4 Changelog parser — `app/changelog.py`

In-house, ~40 lines, **no markdown dependency** (the constrained format
doesn't justify pulling `markdown`/`mistune`):

```python
parse_changelog(text) -> list[Release]
# Release = {version, date, sections: [{title, items: [str]}], unreleased: bool}
```

Splits on `## ` headings, parses the `[ver] — date` line, groups `###`
sections and their `- ` bullets. Items are HTML-escaped at render time
(Jinja autoescape). Parsed result cached (file rarely changes; re-read on
each request is fine at this scale, but cache keyed by mtime is cheap
insurance). Latest release version is compared against `version_info()` to
flag drift in dev.

## 4. UI surfaces

### 4.1 Footer version badge (`base.html`)

Add a slim footer (currently none) inside/after `<main>`:

```
Data Hub · v0.2.0 · a1b2c3d        [Có gì mới →]
```

- Links to `/whats-new`.
- Shows `(dev)` suffix when `source != "build"`.
- Primer-aligned: muted text, small, `--brand` green monogram dot to match
  the app-identity work from `55385b2`. Visible to all logged-in users.
- Version string also injected into a `<meta name="app-version">` for quick
  inspection.

### 4.2 "Có gì mới" page (`GET /whats-new`)

- Auth required (mirrors other UI routes; redirect to `/login` if not).
- New template `whats-new.html` extending `base.html`.
- Renders parsed `CHANGELOG.md`: each release as a card (version badge +
  date), sections as labeled groups, bullets as lists. Newest first.
- Top of page: current running version + build time + git SHA (from
  `version_info()`), so users see exactly what they're on.
- i18n key `nav.whats_new` = "Có gì mới" / "What's new"; reachable from
  footer badge and (optional) the **Cấu hình ▾** nav group.

### 4.3 (Optional, phase 2) "unseen version" dot

A small dot on the footer badge when the user hasn't opened the latest
version's notes. Store last-seen version in a cookie (or user pref). Flagged
**optional** to keep v1 scope tight — decide at implementation time.

## 5. Build / release wiring

### Dockerfile
Add build args + bake to env:
```dockerfile
ARG VERSION=0.0.0
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV DATA_HUB_VERSION=$VERSION DATA_HUB_GIT_SHA=$GIT_SHA DATA_HUB_BUILD_TIME=$BUILD_TIME
```

### docker-compose.yml
`app.build` becomes:
```yaml
build:
  context: .
  args:
    VERSION: ${DATA_HUB_VERSION:-0.0.0}
    GIT_SHA: ${DATA_HUB_GIT_SHA:-unknown}
    BUILD_TIME: ${DATA_HUB_BUILD_TIME:-unknown}
```

### CI deploy step (`.github/workflows/ci-cd.yml`)
Before `docker compose up -d --build`, export:
```bash
export DATA_HUB_VERSION=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)
export DATA_HUB_GIT_SHA=$(git rev-parse --short HEAD)
export DATA_HUB_BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```
(host has the repo via `git reset --hard origin/main`, so SHA is exact.)

The `docker` CI job's smoke build can leave args at defaults.

## 6. Release process (documented in release-engineering.md §1)

Per release: (1) bump `pyproject.toml` version, (2) add a dated section to
`CHANGELOG.md`, (3) commit, (4) tag `vX.Y.Z`, (5) push `main` → auto-deploy.
First tag with this feature = **`v0.2.0`** (release-eng already predicted
this). Update release-eng §1 to mark `/version` **done** and remove it from
open items.

## 7. Files touched

| File | Change |
|------|--------|
| `app/version.py` | NEW — resolver + `version_info()` |
| `app/changelog.py` | NEW — `parse_changelog()` |
| `app/main.py` | `/version` endpoint; inject version into template ctx; `/whats-new` route |
| `app/i18n.py` | `nav.whats_new`, `whats_new.*`, `version.*` keys (vi + en) |
| `app/templates/base.html` | footer with version badge |
| `app/templates/whats-new.html` | NEW page |
| `app/templates/_client_nav.html` | (optional) link under Cấu hình ▾ |
| `CHANGELOG.md` | NEW — seed 0.1.0 + 0.2.0 |
| `Dockerfile` | build args → env |
| `docker-compose.yml` | `build.args` |
| `.github/workflows/ci-cd.yml` | export version env before compose build |
| `docs/release-engineering.md` | mark `/version` done; document release process |
| `pyproject.toml` | bump to `0.2.0` |

## 8. Tests

- `test_version_endpoint`: `/version` returns required keys; unauth OK.
- `test_version_resolver`: env precedence > pyproject/git > unknown;
  `source` field correct.
- `test_changelog_parser`: parses versions/dates/sections/bullets; handles
  `[Unreleased]`; malformed input degrades gracefully (empty list, no
  crash).
- `test_whats_new_page`: auth required (redirect when logged out); renders
  latest version + at least one release card when logged in.
- Escape check: a `<script>` bullet renders escaped, not executed.

## 9. Done criteria + manual test plan

**Done when:**
1. `curl localhost:8754/version` returns version + sha + build_time.
2. Footer badge shows `vX.Y.Z · <sha>` on every page; `(dev)` locally.
3. `/whats-new` renders CHANGELOG with current-version header; reachable
   from the badge; auth-gated.
4. A built image carries the right version (build arg flows through);
   `source="build"`.
5. release-eng §1 updated; `pyproject` bumped; `v0.2.0` tagged.
6. `uv run pytest -q` green.

**Manual test:**
```bash
# dev — shows (dev) + live git sha
uv run uvicorn app.main:app --port 8754 --workers 1
#   open /whats-new, check footer badge, curl /version
# built — shows baked version, source=build
DATA_HUB_VERSION=0.2.0 DATA_HUB_GIT_SHA=$(git rev-parse --short HEAD) \
  DATA_HUB_BUILD_TIME=$(date -u +%FT%TZ) docker compose up -d --build
curl -s localhost:8754/version | jq
```
Screenshots (footer badge light/dark + whats-new page) committed to this
folder's `screenshots/` at implementation time, per feature-folder
convention.

## 10. CO follow-up (deferred — brief after DH ships)

CO is the code seed (`~/workspace/client/barry-CO-main`) and also lacks any
`/version`/changelog. After DH ships, write an outbound prompt in
`.ai/sister-app-notes/` (do NOT write code into CO from this repo) telling
CO to mirror: same `/version` shape, footer badge, curated `CHANGELOG.md`,
What's-new page — but CO's own `--brand` (violet, per the pending app-identity
prompt). The structure transfers ~1:1 since DH descends from CO's templates.
Bonus: with both apps exposing `/version`, each can display the other's
version on its cross-app/integration status panel.

## 11. Open questions / scope guards

- **Markdown renderer:** brief assumes in-house parser (no dep). If
  CHANGELOG ever needs rich markdown (links, bold, nested lists), revisit
  and pull `markdown`. Not now (no over-engineering).
- **Unseen-version dot (§4.3):** optional, lean toward deferring to phase 2.
- **GHCR / image tags:** still deferred (single deploy host) — unchanged by
  this feature; build-on-host with baked args is enough.
- **`[Unreleased]` section:** include in CHANGELOG but the footer badge
  always shows the *built* version, not Unreleased.
