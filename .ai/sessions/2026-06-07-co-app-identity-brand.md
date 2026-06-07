# Session 2026-06-07 — CO app-identity brand chrome

## Goal
CO + Data Hub share the Primer console design system → look near-identical; operators can't
tell which app they're in. Data Hub (commit `dbd85fb` in TinsuAI/data-hub) added an app brand
signal (green `#1a7f37`/`#2ea043`): brand color on monogram, topnav bottom border, full-viewport
frame. Add the symmetric signal to CO in a clearly different hue.

## What was done (mirrors Data Hub dbd85fb)
- `app/static/css/app.css`: `--brand` + `--brand-foreground` in BOTH theme blocks
  (light `#8250df`/dark `#a371f7`, foreground `#ffffff`). `.brand-mark` → filled brand badge
  (bg `--brand`, color `--brand-foreground`, border `color-mix(--brand 55%, transparent)`).
  `.topnav` border-bottom → `2px solid color-mix(--brand 35%, --border)`. New `.app-frame`
  overlay: `position:fixed; inset:0; z-index:1000; pointer-events:none; border:3px solid --brand`.
- `app/templates/base.html`: `<div class="app-frame" aria-hidden="true">` as first child of
  `<body>` (shared base — all real pages extend it; only partials don't).

## Decisions
- Hue = **purple** (`#8250df`/`#a371f7`), confirmed with user before ship. Hard rule satisfied:
  not green (Data Hub), not the shared `--primary` blue — so it can't read as success or a
  primary button.
- Identity chrome ONLY. `--primary` (blue) still drives links/buttons/active states; no surfaces
  tinted. Frame is `pointer-events:none` (never blocks clicks / shifts layout). Light + dark
  both first-class; `--brand-foreground` white passes contrast on both brand shades.

## Verification
- Full suite `uv run pytest` → **484 passed, 8 skipped**.
- Deployed: commit `1f2b6dd` → CI run 27089894162 (tests → build → deploy tinsu → nightly) all ✓.
- **Live on prod** (authed `claude-check@local`): computed `--brand`=#8250df, `.brand-mark`
  bg rgb(130,80,223), `.app-frame` border rgb(130,80,223)/3px. Local + prod screenshots under
  `.ai/screenshots/2026-06-07-co-app-identity-brand/` (co-light/dark, prod-light).
- Note: bare `/static/css/app.css` on prod still served the STALE Cloudflare copy (4h TTL); the
  app's content-hashed `asset_url()` serves the new CSS — confirmed via computed styles, not the
  bare path (memory `static-asset-cache-busting`).

## Open items
- None. (CO repo TinsuAI/co; both `origin` + `tinsu` remotes point at it; pushed `origin main`.)
