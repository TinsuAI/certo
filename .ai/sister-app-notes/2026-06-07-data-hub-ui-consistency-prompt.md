# Outbound prompt → Data Hub agent: align Data Hub UI with the Barry CO "Primer console" redesign

Copy everything below the line into the Data Hub agent.

---

## Task
Barry CO (the sister app operators use alongside Data Hub) just shipped a UX/UI redesign the
team is happy with. Re-skin and lightly re-organize the **Data Hub** UI to the **same design
system** so the two apps feel like one product as operators move between them. This is a
visual + IA consistency pass, NOT a feature change. Match CO; don't invent a new look.

Work like a pragmatic senior engineer: discover Data Hub's current UI first, propose the
mapping, then apply in phases, verify, and don't break the heavy existing pages.

## The design language (adopt as-is)
**"GitHub Primer operations console"** — a calm, neutral, data-dense *tool* aesthetic, NOT a
bold/marketing SaaS dashboard. This is the deliberate decision CO landed on after rejecting
several bolder palettes: operators stare at these screens all day, so the chrome should recede
and the data should lead.

Principles:
- Neutral slate foundation + **ONE blue accent** used only for primary actions / links / active
  state. Don't splash the accent around.
- **Semantic colors** (green/amber/red) reserved for status only.
- **Solid 1px borders**, **small radius** (6–8px), **near-zero shadows** (flat; delineate with
  borders, not elevation), **flat background** (no gradients).
- Strong typographic hierarchy; tables and data are the focus.
- Restraint over boldness. Reference tools: GitHub Primer, Stripe, Linear, Atlassian.
- Support **light + dark**, both first-class.

## Design tokens — copy these exact values (so the two apps match to the pixel)
Map them onto Data Hub's existing CSS custom properties: **keep your variable NAMES, change the
VALUES**. That single move lets your big/complex pages inherit the new look with zero
per-component edits (this is exactly how CO re-skinned a 5,000-line page safely). If Data Hub
doesn't use CSS variables yet, introduce these and route component styles through them.

```css
:root {
  --radius-sm: 6px; --radius-md: 6px; --radius-lg: 8px; --radius-xl: 10px; --radius-pill: 999px;
  --sans: "Manrope", "Segoe UI Variable", sans-serif;
  --mono: "IBM Plex Mono", monospace;
  --space-1: 0.25rem; --space-2: 0.5rem; --space-3: 0.75rem; --space-4: 1rem;
  --space-5: 1.5rem; --space-6: 2rem; --space-7: 3rem;
  --fs-xs: 0.72rem; --fs-sm: 0.82rem; --fs-md: 0.92rem; --fs-lg: 1.1rem; --fs-xl: 1.4rem; --fs-2xl: 1.9rem;
  --lh-tight: 1.2; --lh-normal: 1.5;
}
body[data-theme="light"] {
  color-scheme: light;
  --background: #f6f7f8; --background-top: #ffffff;
  --background-accent: rgba(31,111,235,0.04); --background-accent-2: rgba(31,111,235,0.02);
  --foreground: #1f2328; --foreground-soft: #424a53; --foreground-muted: #656d76;
  --card: #ffffff; --card-muted: #f6f8fa; --menu-surface: #ffffff;
  --surface-subtle: #f6f8fa; --surface-hover: #eef1f4;
  --surface-overlay: rgba(255,255,255,0.95); --surface-input: #ffffff;
  --border: #d0d7de; --border-strong: #afb8c1;
  --primary: #1f6feb; --primary-hover: #1a5fd0; --primary-soft: rgba(31,111,235,0.1); --primary-foreground: #ffffff;
  --success: #1a7f37; --warning: #9a6700; --error: #cf222e; --info: #1f6feb; --stale: #656d76;
  --success-soft: rgba(26,127,55,0.12); --warning-soft: rgba(154,103,0,0.13);
  --error-soft: rgba(207,34,46,0.11); --info-soft: rgba(31,111,235,0.1);
  --shadow-md: 0 1px 0 rgba(31,35,40,0.04); --shadow-lg: 0 8px 24px rgba(31,35,40,0.12);
}
body[data-theme="dark"] {
  color-scheme: dark;
  --background: #0d1117; --background-top: #010409;
  --background-accent: rgba(56,139,253,0.1); --background-accent-2: rgba(56,139,253,0.06);
  --foreground: #e6edf3; --foreground-soft: #c9d1d9; --foreground-muted: #8b949e;
  --card: #161b22; --card-muted: #0d1117; --menu-surface: #161b22;
  --surface-subtle: #161b22; --surface-hover: #21262d;
  --surface-overlay: rgba(13,17,23,0.9); --surface-input: #0d1117;
  --border: #30363d; --border-strong: #444c56;
  --primary: #388bfd; --primary-hover: #58a6ff; --primary-soft: rgba(56,139,253,0.15); --primary-foreground: #ffffff;
  --success: #3fb950; --warning: #d29922; --error: #f85149; --info: #58a6ff; --stale: #8b949e;
  --success-soft: rgba(63,185,80,0.15); --warning-soft: rgba(210,153,34,0.15);
  --error-soft: rgba(248,81,73,0.15); --info-soft: rgba(88,166,255,0.15);
  --shadow-md: 0 0 0 1px rgba(1,4,9,0.0); --shadow-lg: 0 16px 40px rgba(1,4,9,0.5);
}
```
Theme is toggled via `data-theme` on `<body>` (light/dark). Sweep any hardcoded color literals
in your CSS onto these tokens, or the palette swap will leave stale-colored borders/shadows.

## Components / patterns to mirror
- **Cards / panels:** flat, solid 1px border, no shadow; hover = accent border + subtle muted
  background (no lift/translate).
- **Metric-card dashboard band:** a row of metric cards at the top of each data page — big value
  + small label (+ optional `sub` like a version) + optional tone (`primary` / `warn`). Shows
  the key aggregates at a glance.
- **Grouped nav:** primary workflow first and visually distinct; secondary areas collapsed into
  dropdowns (use `<details>`/`<summary>`, no JS). Flat topnav with a bottom border only;
  declutter it.
- **Status pills** (semantic tone), **monogram avatars** (initials in a tinted square),
  **chips** — all neutral + a single accent/semantic tone.
- Inputs/buttons: small radius, weight ~600 primary button (solid accent), bordered secondary.

## IA / content principles
- Put Data Hub's **primary job** front-and-centre; demote secondary data/config into grouped nav.
- Give each data page an **overview dashboard** — but built **only from cheap aggregates**.
  Never scan a large dataset just to compute a dashboard number. If a real count isn't cheaply
  available, show a qualitative card; **do NOT fabricate a number**. (CO hit this: a list
  endpoint was page-capped at 50, so it returned 50 for every client — rendering that as a
  "total" was misleading. Don't render capped/partial counts as totals; expose real
  totals/aggregates server-side instead.)
- Feature-detect optional data and degrade gracefully.

## Process / rigor (this is what made it safe — do the same)
1. **Token-value swap, names unchanged** so heavy pages inherit without per-component edits.
2. **WCAG AA contrast gate:** check the critical pairs in BOTH themes (foreground/background,
   foreground-muted/card, primary-foreground/primary, error/card) before shipping.
3. **Screenshot gate** for any page with fixed-width tables / bespoke layouts: capture
   before/after at a fixed viewport; only **color** may change on classes those pages reuse —
   **freeze padding/font-size/geometry** there (change geometry only on new/dashboard-only
   components).
4. **Run the FULL test suite before pushing** to an auto-deploy branch — a hand-picked subset
   misses integration/UI-copy tests; update assertions that legitimately changed, preserving
   their intent.
5. **Get sign-off on the visual direction early** with real rendered screenshots (light + dark)
   — don't guess; CO cycled through ~4 palettes before this one stuck. Show, don't tell.

## Suggested phasing
Discover current UI → 0a color tokens (+ literal sweep + contrast) → 0b spacing/type scale on
new components → shell + grouped nav → primary-workflow landing → per-page overview dashboards
→ config grouping. Ship/verify per phase; keep the heavy existing pages working throughout.

## Deliverable
A Data Hub UI that is visually indistinguishable in palette/feel from CO, with the same
component vocabulary and the same restraint, verified in both themes with the full test suite
green. Reference implementation (if you can see the CO repo): `app/static/css/app.css` (tokens
+ components), `app/templates/_client_nav.html` (grouped nav), `_source_stats.html` +
`client_context.source_stats` (metric dashboards), `clients.html` / `workspace.html` (cards +
landing).
