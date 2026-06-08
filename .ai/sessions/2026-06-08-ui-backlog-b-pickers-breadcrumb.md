# Session: UI backlog B (modal pickers, table widths, full-width) + breadcrumb nav

Date: 2026-06-08. HEAD at end: `7253412` (deployed prod + demo, verified).

## What Was Done

Cleared backlog section **B** (`.ai/BACKLOG.md`) + added breadcrumb navigation, all
shipped to prod and browser-verified.

- **B1 — modal pickers (Đổi công ty / Đổi hồ sơ).** Replaced two redirect links with
  lazy-fetch modals. New fragment endpoints `GET /clients-picker` (pages.py) +
  `GET /clients/{id}/co-case-picker` (co_case.py); templates `_picker_clients.html` /
  `_picker_cases.html`; one generic picker script in `base.html` bound to
  `[data-picker-open]` (`data-picker-url` + `data-picker-target` → fetch → inject into
  `[data-picker-body]`); CSS `.picker-*`. Current item highlighted.
- **B3 — origin material table column widths.** Root cause: a `select` checkbox column was
  inserted as column 1 but widths still used `th:nth-child(N)` numbered for the old
  11-column layout → every width shifted one column (STT 7.2rem, Mã NVL 22rem, Tên NVL
  6rem). Switched widths to `[data-origin-column]` selectors. Also `.origin-col-select`
  `width:1%`→`2.6rem` (1% collapses under `table-layout:fixed` and clipped the checkbox).
- **B4 — full-width case detail.** Side margins came from `.shell { width: min(1480px, …) }`
  (the `.app-frame` brand border is just a fixed overlay, no margin). Added
  `{% block shell_modifier %}` to `<main class="shell …">` in base.html; co_case.html sets
  `shell-wide` only when `co_case_active_step != "index"`; CSS `.shell-wide { width:
  calc(100vw - 32px); max-width:none }`. Scoped so list/catalog/etc. stay centered.
- **Breadcrumb nav (user request after B).** Added a hierarchical breadcrumb in
  `_client_nav.html` (the partial included on every client + case page): `Công ty › {company}
  › {section / Hồ sơ C/O} › {case_code}`. Adapts via `active` + `co_case_active_step`;
  ancestors are links. CSS `.breadcrumb*`.
- **B2 — discovery only** (`/discover`). Brief `.ai/features/2026-06-08-workflow-step-status-display.md`.
  No code. Found Phase 2 already shipped (see Decisions).
- **Prod auth fix** (found during prod verify): client picker 403 → `/clients/picker` moved
  to `/clients-picker`; `should_guard_path` whitelist; regression test
  `tests/test_co_auth_path_guard.py`.

Commits: `0de7525` (feat: pickers/widths/fullwidth/breadcrumb), `e3f26a2` (docs: backlog +
B2 brief), `7253412` (fix: auth 403). All pushed; prod + demo on `7253412`.

## Decisions Made

- **B1 data loading = lazy-fetch fragment** (user chose over server-render). No per-page query
  cost; reuses the existing `.modal-backdrop`/`.confirm-modal` pattern + a shared JS helper.
- **Cross-client vs per-client routes.** Client picker is cross-client → must be a top-level
  path (`/clients-picker`), NOT `/clients/{x}` — otherwise `guard_response` reads segment-2 as
  a `client_id` and 403s it. Per-client case picker stays under `/clients/{id}/...`. Captured in
  memory `cross-client-fragment-route-403`.
- **B2 = full `/discover`, no implementation** (user chose over a quick relabel). Brief recommends
  deriving step-3 status from `origin_sheet_states` and unifying with `co_case_status_view`.
- **B4 scoping via a Jinja block** (not a body class or JS) — clean, server-side, zero risk to
  the global brand frame.
- **Committed straight to `main`** (project convention — deploy triggers on push only) and pushed
  on explicit user request; verified prod after each deploy.

## What Didn't Work

- **`/clients/picker` as the client-picker route.** Passed locally + all 521 file-mode tests, but
  403'd on prod. `guard_response` runs only when auth is ON (local `CO_AUTH_REQUIRED=0`), so the
  per-client check that mis-parsed `picker` as a client_id never fired locally. Lesson: anything
  touching route-guard/auth must be browser-tested on prod, not just locally/unit.

## Open Items

- **B2 implementation** — next via `/tdd` (`co_case_step_status` + `co_case_workflow_steps` are
  pure functions). Brief is ready; Phase 2 dependency already satisfied.
- **D1** (audit delta-vs-full / DH refresh) remains the highest-risk open backlog item (SAI TỒN).
- Two prior-session logs still uncommitted in the working tree (versioning-changelog,
  origin-cold-load-perf) — unrelated to this session; left as-is.
- B2 brief open questions: show "M/N chốt" count on stepper? tighten "Chứng từ" beyond
  any-file-present? collapse review+preview into one `attention`?
