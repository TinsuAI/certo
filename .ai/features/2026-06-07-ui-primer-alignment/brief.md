# UI consistency pass — align Data Hub with Barry CO "Primer console"

**Date:** 2026-06-07
**Type:** Visual + IA consistency (no feature change)
**Driver:** `barry-CO-main/.ai/sister-app-notes/2026-06-07-data-hub-ui-consistency-prompt.md`

## Goal
Re-skin and lightly re-organize the Data Hub UI to Barry CO's "GitHub Primer
operations console" design system, so operators moving between the two sister
apps feel one product. Neutral slate + one blue accent, flat 1px-bordered
surfaces, small radius, near-zero shadow, data-dense, light + dark first-class.

## What changed

### Phase 0a — token-value swap (`app/static/css/app.css`)
DH and CO already share the **same CSS variable names**, so this was a values-only
swap (names unchanged) — heavy pages inherited the look with zero per-component edits.
- Accent: green `#059669` → CO blue `#1f6feb` (light) / `#388bfd` (dark).
- Radii 8/12/20/26 → 6/6/8/10; added `--radius-pill`.
- Backgrounds: radial-gradient + glassy translucent → flat solid hex.
- Shadows: heavy drop-shadows → near-zero (border delineation).
- Added CO scales `--space-*`, `--fs-*`, `--lh-*`, `--menu-surface`.
- Button: border:0 / weight 700 → 1px border / weight 600.

### Phase 0b — literal sweep + WCAG AA gate
- Replaced live hardcoded literals that wouldn't follow the swap: `.toast`
  (green border), `btn-danger`/`btn-danger-sm` reds, checkbox/prov-toggle/notif
  indigo+green, drift value-chips, ai-panel gradient, auth focus-ring — onto
  tokens / `color-mix(--primary …)`.
- Aliased the legacy DH token block (`--accent`/`--surface`/`--text`, indigo)
  onto the CO tokens on `body[data-theme]` selectors; removed redundant
  dark-theme hex overrides.
- Dead CSS (`flash-`, `topnav-links`, `tag-mode` — 0 template uses) left untouched.
- **Contrast gate:** all critical pairs AA in both themes (dark primary-fg/primary
  is AA-large at 3.34, matching CO's shipped value for bold button text).

### Phase 1 — grouped nav + flat components (`_client_nav.html`)
- 13-tab flat strip → **Overview · Dữ liệu ▾ · Uploads · Trợ lý · Cấu hình ▾**.
  Secondary areas collapsed into `<details class="nav-menu">` dropdowns (no JS).
  Ported CO's `nav-menu` CSS; `.client-tabs { overflow: visible }` so panels show.
- Cards: hover = accent border + muted bg, **no lift** (removed translateY).

### Phase 2 — per-page metric bands (`clients/_metric_dash.html` + `data-dash` CSS)
Each data page gained an overview band built **only from cheap index-backed
aggregates already in context** — never a large-dataset scan, never a
capped/partial count rendered as a total (the CO pitfall). Filter-dependent
totals are labeled "Kết quả lọc"; pages with no real number degrade to fewer
cards rather than fabricating.
- **Catalog:** Tổng mã + per-category (NVL/BTP/TP) + chưa-đăng-ký / chưa-resolve (warn).
- **BCCT:** Tổng dòng + Nhập/Xuất split + số năm.
- **BOM:** Sản phẩm có BOM + phiên bản + stale (warn) + multi-version + XK có BOM.
- **Declarations:** Tổng tờ khai + có-file / thiếu-file (warn).
- **Proposals:** total + per-status (warn on pending).

Routes touched: `catalog.py`, `bcct.py`, `bom.py`, `declarations.py`, `proposals.py`.

## Verification
- Full suite: **1390 passed, 16 skipped** (after Phase 1 and again after Phase 2).
- WCAG AA contrast gate both themes.
- Band values cross-checked: sums reconcile (BCCT 38287+916=39203; catalog
  283+153+21=457; declarations 1477+426=1903).
- Screenshots both themes — see `screenshots/` (before/after pairs + open nav dropdown).

## Done criteria
Palette/feel/component-vocabulary indistinguishable from CO, grouped nav, cheap
per-page dashboards, both themes verified, full suite green. ✅
