# Session — Elegant error handling for UI routes (2026-06-19)

Shipped end-to-end: UI page routes no longer leak raw `{"detail": ...}` JSON on
errors; they render a friendly, Vietnamese-localized error page (or bounce to
login), while the JSON API contract for sister apps is preserved untouched.
Built → tested → real-data verified → PR #12 → merged → deployed to prod
(`ttdatahub.tinsu.ai`, git_sha `f8c3282`).

## What Was Done

- **Global exception handlers** in `app/main.py`:
  `StarletteHTTPException`, `RequestValidationError`, catch-all `Exception`.
  - `_wants_json_error(request)` decides JSON vs HTML: true for `/v1/*`,
    `/api/v1/*`, and programmatic fetch/XHR (`Sec-Fetch-Mode:
    cors|same-origin|no-cors`, or `X-Requested-With`). JSON path delegates to
    FastAPI's default handlers (contract unchanged).
  - UI navigation: `401` → `303 /login?next=<path+query>`; any other status →
    `error.html` with a localized title (by status) + the route's actual
    `HTTPException.detail` as the body (detail-less raises fall back to localized
    copy; the bare HTTP phrase like "Not Found" is treated as detail-less).
    Unhandled `Exception` → generic 500 page; `str(exc)` never shown (leak-safe).
- **`app/templates/error.html`** (extends base.html) + `.error-page*` CSS in
  `app/static/css/app.css`. Renders in light + dark, logged-in (home CTA) or out
  (login CTA).
- **i18n** (`app/i18n.py`): `error.*` keys (vi+en) for titles/bodies;
  `ROUTE_DETAIL_VI` (exact map) + `ROUTE_DETAIL_VI_PREFIX` (dynamic
  `"<prefix>: <value>"`, prefix translated + value preserved) +
  `translate_detail(detail, lang)` — lang-aware, applied ONLY at the HTML render
  layer.
- **Tests:** `tests/test_error_pages.py` — 9 tests (login bounce, query
  preservation, 404 HTML, 404 detail vi-localized / en-kept, `translate_detail`
  unit exact+dynamic+passthrough, `/v1/hub` JSON, `/api/v1` JSON, fetch→JSON,
  navigation→page). Full suite: **1561 passed, 16 skipped**.
- **Feature folder:** `.ai/features/2026-06-19-elegant-error-pages/` —
  `brief.md`, `ui_smoke.py`, screenshots (`01_unauth_bounces_to_login`,
  `02_404_light`, `03_404_dark`).
- **CHANGELOG:** entry under `[Unreleased]` (VN, "Sửa"). No `API_CHANGELOG.md`
  bump — `/v1/hub` surface unchanged.
- **Shipped:** PR #12 (merge commit `f8c3282`), CI green (Test + Docker build +
  Deploy to tinsu), prod verified live, local `main` synced.
- Memory written: `project_central_error_handlers` (+ MEMORY.md pointer).

## Decisions Made

- **Route messages by path, not by `Accept` alone.** Path convention
  (`/v1`, `/api/v1`) is the deterministic JSON signal; `Sec-Fetch-Mode`/
  `X-Requested-With` extend it to fetch/XHR (the chat widget lives outside
  `/api/v1`). Top-level navigations (`Sec-Fetch-Mode: navigate`) get HTML.
- **Show the route's real message for all client errors**, not just 400/422.
  The user explicitly wanted the actual error content visible.
  `HTTPException.detail` is author-controlled → safe to show. Only the
  unhandled-`Exception` 500 stays generic (could leak SQL/paths/internals).
- **Localize at the render layer, not at ~150 call sites.** A central
  `i18n.translate_detail` map (exact + dynamic prefixes) translates only when
  rendering the HTML page. This (a) keeps the JSON/API detail (sister-app
  contract + machine codes) untouched by construction, (b) avoids touching
  API-route raises mixed into the same files (e.g. `bom.py`), (c) is one source
  of truth. Unknown details pass through unchanged.

## What Didn't Work

- **First restart attempts left the server running STALE code.** `--workers 4`
  spawns worker processes whose cmdline is the multiprocessing-spawn stub, so
  `pkill -f "uvicorn ... port 8754"` killed only the master; orphaned workers
  (reparented to init) kept holding :8754 and serving old code. Live checks
  showed pre-change behavior while tests (in-process) passed. Fix: kill master,
  then `kill -9 $(fuser 8754/tcp)` for orphans, confirm port free, relaunch.
- **`nohup uvicorn ... &` inside a `run_in_background` Bash task** got killed
  with the task's process group (exit 144 / "Address already in use" on the next
  start). Fix: `exec uv run uvicorn ...` as the background task itself.
- **`git pull --ff-only` failed** with "cannot pull with rebase: You have
  unstaged changes" because the repo sets `pull.rebase=true`. Used
  `git merge --ff-only origin/main` instead — fast-forwards without rebase and
  preserves the pre-existing unstaged files.

## Open Items

- Carry-overs (not touched this session): CO scan question (PR #11); Johnson
  `material_group` prod backfill (0/13,594 prod); `docs/agency-staff-guide`
  branch `d5ae3ab` unpushed.
- Optional: a few dynamic route details outside `ROUTE_DETAIL_VI_PREFIX` (rare
  admin/tampered-param paths) still render English — extend the prefix map if any
  shows up in real use.
- Local repo still has the long-standing pre-existing dirty tree
  (`.ai/BACKLOG.md`, `uv.lock`, untracked sessions/docs/scripts) — not from this
  work; left alone.
