# Outbound prompt → Barry CO agent: add reciprocal per-app identity marker

Context for us (not the CO agent): Data Hub shipped its half in `dbd85fb`
(`--brand` = green monogram + topnav border + 4-side viewport frame). CO needs
the mirror in a DIFFERENT color so operators can tell the two apps apart.
Copy everything below the line into the CO agent.

---

## Task
Data Hub and Barry CO now share the same "Primer console" design system, so the
two apps look almost identical — operators can't tell at a glance which one
they're in. Data Hub just added a per-app **identity marker**: a brand color
(Data Hub = **green**) applied to the monogram badge, the topnav bottom border,
and a fixed brand-colored frame around the whole viewport. Add the **reciprocal**
marker to CO in a clearly different color, so switching between the apps is
unmistakable.

This is identity chrome only — **do NOT touch the shared blue action accent**
(`--primary` stays the color for links / buttons / active state). Don't tint
surfaces. Support light + dark equally.

## Brand color
Pick a `--brand` that is distinct from BOTH Data Hub's green AND the shared blue
`--primary` (so it doesn't read as "success" or as a primary action).
**Recommended: violet** — `#8250df` (light) / `#a371f7` (dark). Confirm the exact
hue with the user before shipping; the only hard rule is **not green** (that's
Data Hub) and not the blue primary.

## Implementation (mirror Data Hub exactly so the two frames match in weight)

1. **Tokens** — add to BOTH theme blocks in `app/static/css/app.css`:
   ```css
   /* body[data-theme="light"] */
   --brand: #8250df;
   --brand-foreground: #ffffff;
   /* body[data-theme="dark"] */
   --brand: #a371f7;
   --brand-foreground: #ffffff;
   ```

2. **Monogram** — make `.brand-mark` a filled brand badge:
   ```css
   .brand-mark {
     /* keep existing size/font */
     border: 1px solid color-mix(in srgb, var(--brand) 55%, transparent);
     background: var(--brand);
     color: var(--brand-foreground);
   }
   ```

3. **Topnav bottom border** — brand-tinted (the header is sticky, so this stays
   on screen):
   ```css
   .topnav { border-bottom: 2px solid color-mix(in srgb, var(--brand) 35%, var(--border)); }
   ```

4. **4-side viewport frame** — overlay only, never blocks clicks or shifts layout:
   ```css
   .app-frame {
     position: fixed; inset: 0; z-index: 1000;
     pointer-events: none; border: 3px solid var(--brand);
   }
   ```
   Add `<div class="app-frame" aria-hidden="true"></div>` as the first child of
   `<body>` in `base.html`. If the topnav currently has a `border-top` brand bar,
   remove it (the frame's top edge replaces it — avoids a double line).

## Constraints / done criteria
- `--brand` is identity-only; `--primary` (blue) remains the action accent.
- Light + dark both first-class; verify `--brand-foreground` on `--brand` meets
  WCAG (AA-large is fine for the small bold monogram text).
- The frame must not block interaction (`pointer-events: none`) or change layout.
- Run the FULL test suite before pushing to an auto-deploy branch.
- Result: CO is instantly distinguishable from Data Hub (green) when switching.

## Reference (Data Hub side)
Commit `dbd85fb` in `TinsuAI/data-hub` — `app/static/css/app.css` (`--brand`,
`.brand-mark`, `.topnav`, `.app-frame`) + `app/templates/base.html` (the
`.app-frame` div). Data Hub `--brand` = `#1a7f37` / `#2ea043` (green); pick a
non-green, non-blue hue for CO.
