# UI redesign contract — CO + Data Hub, 2026-08-20

One visual system for both apps, ported from the reference build at
`reference/preview-src-styles.css` (source: `custom-kie/design/hifi`, an
Audit-HQ / GOV.UK / USWDS derived system). Every agent working this feature
reads THIS file. Do not read the 2.6 MB `dist/preview.html`.

Goal, in the user's words: the current UI is "rối rắm và phức tạp không cần
thiết". Target: elegant, professional, dense, government-grade. Fewer surfaces,
one persistent grouped sidebar, calm navy chrome, tabular numerics everywhere.

## Non-negotiables

- **Never push. Branch only.** Both repos deploy production on push to `main`.
  Commit to `redesign/2026-08-ui` in this worktree, nothing else.
- Commit messages English, small and focused, **no AI/co-author trailers**.
- On-screen text Vietnamese with full accents. Identifiers stay English/code
  (`status`, `under_review`, `E31`, `CT-205`).
- `uv run pytest` must pass before you commit. CO also runs `npm test`.
- CO: no raw `/v1/hub` strings outside `app/data_hub_client.py` — a guardrail
  test fails the run.
- Reskin templates **in place**. Do not regenerate a template wholesale.
  `app/templates/co_case.html` is 7,561 lines; in-app nav imports the page via
  `importNode`, so an inline `<script>` never runs — new behaviour goes into
  `refreshCaseShellInteractions`, and you verify by clicking a workflow step,
  not by pressing F5.
- CSS edits are **append-only under your own marked section** when more than one
  agent is live in this worktree. Stage explicit paths on commit; never
  `git add -A` — you will scoop another agent's half-finished edits.
- Structural flow surgery (route changes, step logic, endpoint contracts) is
  **out of scope this round**. Nav/IA-level edits and a written proposal only.

## Live servers (already running, `--reload` on)

| App | URL | Notes |
|---|---|---|
| CO | http://127.0.0.1:8001 | auth off locally, real data, points at DH below |
| Data Hub | http://127.0.0.1:8754 | login `admin@data-hub.local` / `admin123` |

Port 8754 is pinned — CO's JWT issuer validation expects exactly that origin.
Do not start a second server on another port.

## 1. Token remap (Phase A, do this first)

Both apps are already ~100 % `var()`-driven with the palette on
`body[data-theme="light"|"dark"]` in `app/static/css/app.css`. Redefining the
values reskins every page at once. **Keep every existing token name** — renaming
breaks 1,164 (CO) / 524 (DH) call sites.

Light theme — replace the values in `body[data-theme="light"]`:

```
--background:          #f6f7f9
--background-top:      #ffffff
--background-accent:   rgba(29,53,87,0.04)
--background-accent-2: rgba(29,53,87,0.02)
--foreground:          #0f172a
--foreground-soft:     #475569
--foreground-muted:    #616e83
--card:                #ffffff
--card-muted:          #f8fafc
--menu-surface:        #ffffff
--surface-subtle:      #f8fafc
--surface-hover:       #f1f5f9
--surface-overlay:     rgba(255,255,255,0.96)
--surface-input:       #ffffff
--border:              #e2e8f0
--border-strong:       #cbd5e1
--primary:             #1d3557
--primary-hover:       #16294a
--primary-soft:        #eef2f7
--primary-foreground:  #ffffff
--success:             #166534
--warning:             #92400e
--error:               #991b1b
--info:                #1e40af
--stale:               #616e83
--success-soft:        #dcfce7
--warning-soft:        #fef3c7
--error-soft:          #fdecec
--info-soft:           #dbeafe
--shadow-md:           0 1px 2px rgba(15,29,59,.06)
--shadow-lg:           0 12px 32px rgba(15,29,59,.14)
```

Add these new tokens to the same block (referenced by the components below):

```
--brand-50:#eef2f7  --brand-100:#d6dfeb  --brand-200:#b9c8dd
--brand-500:#1d3557 --brand-600:#16294a  --brand-700:#0f1d3b
--logic-50:#eef2ff  --logic-100:#e0e7ff  --logic-200:#c7d2fe
--logic-500:#4338ca --logic-600:#3730a3  --logic-700:#312e81
--surface-sunk:#f1f5f9
--critical-bd:#f5c2c2  --warning-bd:#fcd99a
--info-bd:#bfdbfe      --success-bd:#bbf7d0  --muted-bd:#e2e8f0
--header-h:52px  --side-w:228px
```

**App identity split — this is the one rule that separates the two apps.**
The reference system says: *data = navy, logic = indigo. Never mix them.*

- Data Hub is the data plane → `--brand: #1d3557` (navy).
- CO is the logic/calculation plane → `--brand: #4338ca` (indigo).

`--brand` drives app-identity chrome only: monogram, header accent, viewport
frame. Actions (links, primary buttons, active states) stay on `--primary`
navy in **both** apps, so a user moving between them keeps one action colour.

Dark theme — keep it working, shift GitHub-grey to slate/navy:

```
--background:#0f172a  --background-top:#0b1220  --card:#1e293b
--card-muted:#0f172a  --menu-surface:#1e293b   --surface-subtle:#1e293b
--surface-hover:#334155 --surface-input:#0f172a
--border:#334155      --border-strong:#475569
--foreground:#e2e8f0  --foreground-soft:#cbd5e1 --foreground-muted:#94a3b8
--primary:#7da2d1     --primary-hover:#9bbbe4   --primary-soft:rgba(125,162,209,.16)
--success:#4ade80 --warning:#fbbf24 --error:#f87171 --info:#7da2d1
```

## 2. Typography

Replace the Google Fonts link in `app/templates/base.html`:

```html
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;600;700;800&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

Tokens in `:root`:

```
--sans: "Inter","Be Vietnam Pro",-apple-system,"Segoe UI",Roboto,system-ui,sans-serif;
--display: "Be Vietnam Pro","Inter",system-ui,sans-serif;
--mono: "JetBrains Mono","SF Mono","Cascadia Code",Consolas,monospace;
```

`h1..h5` use `--display` with `letter-spacing:-.01em`. Body copy uses `--sans`.

Density — the reference is tighter than the current apps. Retune the scale:

```
--fs-xs:0.72rem  --fs-sm:0.8125rem  --fs-md:0.875rem
--fs-lg:1.05rem  --fs-xl:1.25rem    --fs-2xl:1.4rem
--radius-sm:3px  --radius-md:5px    --radius-lg:8px  --radius-xl:12px
```

Every number in a table cell: `font-variant-numeric:tabular-nums`, right
aligned, `--mono`, 12.5px. Money, quantities, percentages, IDs, hashes.

## 3. Shell — top nav becomes header + left sidebar

This is the structural change that removes most of the "rối rắm". Today both
apps put everything in a top bar plus nested `<details>` dropdowns, so the user
never sees where they are. Replace with:

```
┌──────────────────────────────────────────────── header 52px, navy ──┐
│ [logo] App name        [company switcher]        … user menu        │
├───────────┬─────────────────────────────────────────────────────────┤
│ sidebar   │ rail (pipeline steps, only where a pipeline exists)     │
│ 228px     ├─────────────────────────────────────────────────────────┤
│ grouped   │ view: .wrap max-width 1320px, 16px gap between cards    │
│ nav       │                                                          │
└───────────┴─────────────────────────────────────────────────────────┘
```

- Header: `background: var(--brand-500)`, white text, 52px, holds the brand
  monogram, the company switcher (moved out of the page body — it is a global
  context, not page content), and the user menu. Theme toggle moves into the
  user menu; it does not deserve top-level chrome.
- Sidebar: white, 228px, `border-right`. Items grouped under uppercase 10.5px
  letterspaced group labels. Active item = `--brand-50` background,
  `--brand-600` text, weight 600. Counts render as a mono pill on the right.
- Kill the decorative `.app-frame` and `.shell-noise` layers. The reference has
  no texture; flat surfaces plus one hairline border are the whole look.
- Content: `.wrap { max-width:1320px; margin:0 auto; display:flex;
  flex-direction:column; gap:16px }`.

Class names: keep the existing app class names (`.topnav`, `.shell`,
`.page-bar`, `.tabs`, `.card`, `.badge`, `.btn-primary`) and restyle them.
Introduce new classes only for genuinely new structures (`.side`, `.side-grp`,
`.side-a`, `.rail`, `.rail-s`). Copy the reference declarations for those
verbatim from `reference/preview-src-styles.css`, swapping `--c-*` names for
this repo's token names.

## 4. Component treatment (from the reference)

- **Card** — 1px `--border`, radius 5px, `--shadow-md`. Header row 12/16px with
  a 13px bold title, optional 12px subtitle, actions pushed right by
  `margin-left:auto`. Footer on `--card-muted`, 12px, muted text.
- **Button** — 7px/14px, 13px, weight 500, radius 3px. Primary = navy fill.
  Secondary = white fill, navy text, `--border-strong`. Ghost = transparent
  until hover. Danger = white fill, red border and text. Sizes `sm` (4/10,
  12px) and `xs` (2/8, 11.5px) exist and should be used inside table rows.
- **Badge** — 1px/7px, 11.5px, weight 600, radius 3px, tinted background +
  matching border (`--*-soft` + `--*-bd`). Six kinds: critical, warning, info,
  success, muted, brand.
- **Table** — 9px/14px cells, 13px. Header row on `--card-muted`, 11px
  uppercase, letterspaced .05em, muted, `border-bottom: 1px solid
  --border-strong`, sticky at top. Row hover `--brand-50`. Selected row
  `--brand-50` plus `inset 3px 0 0 var(--brand-500)`. A `.dense` variant at
  6px/10px, 12px is the default for any grid over ~30 rows.
- **Input** — 6px/10px, 13px, `--border-strong`, radius 3px, focus =
  `outline:2px solid var(--primary); outline-offset:-1px`.
- **Stat tile** — label 11px uppercase muted, value 22px `--display` weight
  700, sub-line 11.5px. Never a coloured card background; colour goes on the
  value only when it carries meaning.
- **Note / callout** — left border 3px in the semantic colour, tinted
  background, 12.5px text. Replaces today's toast-styled inline messages.

## 5. What "simpler flow" means this round

Nav/IA level only:

- One sidebar, grouped, always visible. No nested `<details>` menus to reach a
  page. Group labels name the domain step, not the data type.
- Company/client context lives in the header switcher, not repeated in the page
  body on every screen.
- A screen that belongs to a pipeline shows the `rail` under the header with
  every step visible, current step marked, completed steps dimmed. The user can
  always see the whole process and where they are inside it.
- Page header (`.page-bar`) shrinks to: h1 22px, one 13px muted subtitle line,
  actions right. Everything else that lives there today moves into a card.

Anything that needs a route change, a new endpoint, or reordering the workflow
goes into `FLOW-PROPOSAL.md` in this folder — written, not built.

## 6. Proof

Screenshots for this feature go in
`.ai/features/2026-08-20-ui-redesign/screenshots/` written by a `ui_smoke.py`
in the same folder with `OUT = Path(__file__).resolve().parent / "screenshots"`.
Nothing else, nowhere else.
