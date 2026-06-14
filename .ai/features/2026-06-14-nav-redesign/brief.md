# Admin nav redesign (backlog G.1)

**Date:** 2026-06-14 · **Status:** shipped (local; tests + screenshots green)

## Problem

The admin section had no coherent navigation. `admin/users.html` carried a
right-aligned row of six `btn-secondary` links; the other six admin pages each
hand-rolled a *different* ad-hoc set of "← prev / next →" breadcrumb links in
their `page-bar`. No two were consistent, and the orphaned
`/admin/settings/embedding` page wasn't linked from anywhere. Every new admin
surface (Adapter BOM landed 2026-06-14) grew the pile.

## Decision

One shared sub-nav partial, **grouped dropdowns** mirroring the per-client
`_client_nav.html` `<details>` idiom (user pick over a flat tab bar — chosen for
visual consistency with the client nav and room to grow).

`app/templates/_admin_nav.html`:

- **Người dùng** — direct link → `/admin/users` (admin home).
- **Dữ liệu tham chiếu** (dropdown) — Mã loại hình · Preset DNCX · UoM standards.
- **Adapter BOM** — direct link (solitary ingest item; promote to a "Nhập liệu"
  dropdown when a 2nd lands).
- **Hệ thống** (dropdown, **dev-only**) — Service tokens · Cài đặt kỹ thuật ·
  Embedding (the previously-orphaned page, now reachable).

Self-highlights the active group + item from `request.url.path`, so no route
change is needed (every admin route already passes `request` + `active_root`).
Reuses the existing `.tabs` / `.nav-menu` / `.tab-link` CSS; the only CSS change
adds `.admin-tabs` to the `overflow: visible` override so dropdown panels aren't
clipped.

Reference data + Adapter BOM are open to all admins; the Hệ thống group is
withheld for non-dev (its pages 403 otherwise — matches the prior gating).

## Scope note

Targeted the admin bar — the explicit "ad-hoc pile." The per-client nav
(`_client_nav.html`) was already grouped and needed no change; the global topnav
keeps the Admin chip (global) separate from the client tab bar, so global-vs-client
separation already held.

## Changes

- New: `app/templates/_admin_nav.html`.
- `app/static/css/app.css`: `.client-tabs` → `.client-tabs, .admin-tabs`.
- 8 admin templates: include the nav at top of content, drop the divergent
  hand-rolled link rows (`users`, `declaration_types`, `client_type_presets`,
  `service_accounts`, `settings_technical`, `settings_embedding`, `uom`,
  `bom_adapters`).

## Tests

`tests/test_admin_nav.py` (3) — nav renders + active-highlights on all 8 admin
pages (dev), reference-group item is `is-active` on `/admin/uom`, Hệ thống group
hidden for non-dev. Reuses the seeded dev (single-dev invariant). Full suite
1480 passed / 16 skipped.

## UI proof

`screenshots/` — `01_admin_nav` (collapsed), `02_dropdown_open` (Dữ liệu tham
chiếu expanded), `03_active_uom` (active group highlight), each light + dark.
Regenerate: `uv run python .ai/features/2026-06-14-nav-redesign/ui_smoke.py`
against a dev server on :8754.
