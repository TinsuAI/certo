# Elegant error handling for UI routes

**Date:** 2026-06-19
**Status:** Shipped (local), tests green (1557 passed)

## Problem

UI page routes raised `HTTPException` (via `require_user`, `get_client`, mapping
validation, etc.) but the app registered **no exception handlers**. FastAPI's
default handler returned raw JSON to the browser, e.g. a logged-out user hitting
any protected page saw `{"detail":"login required"}` as plain text instead of a
page. Same for 404 (`{"detail":"Client not found"}`), 403, and 500.

Some routes had already worked around this ad-hoc (declarations download bounces
to `/login?next=`; BOM upload renders a recovery template), but routes calling
`require_user()` directly still leaked JSON.

## Fix

Global exception handlers in `app/main.py`. A request "wants a JSON error"
(`_wants_json_error`) when it hits a JSON surface (`/v1/*` + `/api/v1/*`) **or**
is a programmatic fetch/XHR (`Sec-Fetch-Mode: cors|same-origin|no-cors`, or
`X-Requested-With`). Everything else is a top-level navigation → HTML page:

- **API requests** → unchanged: delegate to FastAPI's default
  `{"detail": ...}` JSON handler. Sister-app (CO) contract preserved.
- **UI requests:**
  - `401` → `303` redirect to `/login?next=<path+query>` (preserves the
    destination so login resumes there).
  - any other status → friendly `error.html`: localized title by status (404 →
    "Không tìm thấy trang"…) **plus the route's actual message** as the body
    (`exc.detail`) so the user sees what went wrong. `HTTPException.detail` is
    author-controlled, hence safe to show. A detail-less raise (detail == the
    bare HTTP phrase like "Not Found") falls back to the localized body.
    The detail itself is localized via `i18n.translate_detail` (lang-aware)
    applied **only** at the HTML render layer — the JSON/API path keeps the
    original English/code, so sister-app error contracts are untouched.
    Localization covers both exact messages (`ROUTE_DETAIL_VI`) and dynamic
    `"<prefix>: <value>"` messages (`ROUTE_DETAIL_VI_PREFIX` — e.g. "invalid
    category: 'x'", "Unknown job kind: x", "Parse error: …") where the prefix
    is translated and the dynamic value preserved. Truly unknown details pass
    through unchanged.
  - Unhandled `Exception` (true 5xx) → generic 500 page; `str(exc)` is **never**
    shown (could leak SQL/paths/internals).

Handlers registered: `StarletteHTTPException`, `RequestValidationError`,
catch-all `Exception` (→ 500 page / JSON).

## Files

- `app/main.py` — `_wants_json_error`, `_error_key`, `_render_error_page`, three
  `@app.exception_handler`s.
- `app/templates/error.html` — extends `base.html`; big status code, localized
  title/body, home/login CTA.
- `app/static/css/app.css` — `.error-page*` styles.
- `app/i18n.py` — `error.*` keys (vi + en); `ROUTE_DETAIL_VI` (exact) +
  `ROUTE_DETAIL_VI_PREFIX` (dynamic) + `translate_detail()` (route message
  localization, render-layer only).
- `tests/test_error_pages.py` — 9 tests (login bounce, query preservation, 404
  HTML, 404 detail localized vi / kept en, translate_detail unit
  (exact+dynamic+passthrough), `/v1/hub` JSON, `/api/v1` JSON, fetch→JSON,
  navigation→page).

## Manual test plan

1. Logged out → `GET /clients` → 303 to `/login?next=%2Fclients` (was raw JSON).
2. Logged in → `GET /clients/bad-id` → friendly 404 page (light + dark).
3. `GET /v1/hub/dncxs` (no bearer) → still `{"detail": ...}` JSON 401.
4. `GET /api/v1/.../substitutes` (no cookie) → still JSON 401, not a redirect.
5. Submit BOM/BCCT/BQĐ mapping with a required field unmapped → 400 page showing
   the specific validation message.

## Screenshots

- `01_unauth_bounces_to_login.png` — the reported case, now a real login page.
- `02_404_light.png`, `03_404_dark.png` — friendly 404 in both themes.

## Coverage audit (other error sources)

Swept every error path, not just login/404:
- `raise HTTPException(...)` (401/403/404/400/409/422) — central handler. ✓
- `RequestValidationError`, unhandled `Exception` (500) — central handlers. ✓
- Chat-widget `_widget/*` (JSON fetch outside `/api/v1`) — now JSON via
  `Sec-Fetch-Mode` detection, so the widget surfaces the real message. ✓
- BOM upload parse error (`bom.py:_render_parse_error`) — already a friendly
  HTML recovery page (`bom_upload_error.html`), left as-is. ✓
- `/v1/hub` direct `JSONResponse` error returns (e.g. 409) — already JSON. ✓
- LLM failures inside a widget turn — caught in `agent.py`, appended as a
  friendly assistant message, never a 500. ✓
- `?error=…` redirect flows — surfaced as a toast by `base.html`. ✓

## Notes / scope

- A friendly 500 page renders only when the DB/template still work; a hard DB
  outage falls back to Starlette's bare 500 (acceptable degradation).
- `Sec-Fetch-Mode` is sent by all current browsers; an exotic client that omits
  it on a fetch to a non-`/api/v1` route would get the HTML page — harmless and
  not a real path for the cookie-UI.
