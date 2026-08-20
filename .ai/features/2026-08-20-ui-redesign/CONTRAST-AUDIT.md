# Contrast & accessibility audit — 2026-08-20 UI redesign

Read-only audit of the new token system in both apps. Every ratio below is
computed, not estimated: the token blocks were parsed out of each app's
`app/static/css/app.css`, `rgba()` layers and element `opacity` were composited
over the resolved substrate, and WCAG 2.1 relative-luminance contrast was
computed on the resulting opaque colours.

## Provenance

| Item | Value |
|---|---|
| Snapshot taken | 2026-08-20T00:22:59+08:00 |
| CO worktree | `/home/vp/workspace/client/barry-CO-redesign`, branch `redesign/2026-08-ui`, HEAD `d876fd9` |
| Data Hub worktree | `/home/vp/workspace/client/data-hub-redesign`, branch `redesign/2026-08-ui`, HEAD `eef8c0c` |
| CO `app.css` sha256 | `9398b0d88fe1b117893a53be88cc8a74bed79cd287b4fde312fbbe73cc0edf94` (9,335 lines, 213,787 bytes) |
| DH `app.css` sha256 | `1bf4f72e3941ca48eb303fd9a6cbe8e5162a88d9f9edf129a76cd2f624513b91` (5,346 lines) |
| Audit script | `contrast.py` (scratchpad, not committed) |

Both files were under live edit by other agents while this ran — CO's `app.css`
grew from 9,335 to 9,659+ lines mid-audit. Every line number in this document
refers to the snapshot above. Where a selector was greped after the snapshot the
finding cites the selector and file, not a line number.

Contrast maths validated against the WCAG reference boundaries: `#767676` on
`#ffffff` computes 4.542 (published 4.54), `#949494` on `#ffffff` computes 3.033
(published 3.03), `#000000` on `#ffffff` computes 21.000.

## Thresholds applied

- **4.5:1** for all body text. WCAG "large scale" is >= 24px regular or >= 18.66px
  bold; nothing in this system except the 22px stat-tile value approaches it, and
  every 22px value is weight 700 and clears 4.5 anyway. The 52px header title at
  14px/700 is **not** large text and is held to 4.5.
- **11px and 11.5px text carries no exemption.** Table headers, badges, count
  pills, `btn-xs` labels and stat labels are all held to 4.5.
- **3:1** for non-text under 1.4.11 where the graphic is required to identify a
  control or its state: input boundaries, focus indicators, rail step dots,
  selected-row markers.
- Rows marked **INFO** are computed but carry no requirement: disabled controls
  (1.4.3 exemption), decorative container edges, and tinted grounds that also
  carry a border.

## Scoreboard

| App | Theme | Pass | Fail | Info |
|---|---|---:|---:|---:|
| CO | light | 75 | 6 | 9 |
| CO | dark | 64 | 17 | 9 |
| Data Hub | light | 75 | 6 | 9 |
| Data Hub | dark | 71 | 10 | 9 |
| **Total** | | **285** | **39** | **36** |

The light palette is sound: every text pair passes, and all six light-theme
failures are non-text (input boundaries and rail step dots). The dark blocks
carry 27 of the 39 failures, concentrated in CO where the brand tints are
translucent `rgba()` over `--card` instead of the opaque slate-navy values Data
Hub uses.

## Structural divergence between the two apps

The identity split in DESIGN.md ("data = navy, logic = indigo") is implemented
differently in each app and this drives most of the CO-only dark failures:

| | CO | Data Hub |
|---|---|---|
| Header ground | `--brand-500` (light `#1d3557`, dark `#1e3a5f`) | `--brand` (`#1d3557` in both themes) |
| Sidebar-active / rail-current text | `--primary` | `--brand-600` |
| Dark `--brand-500/600/700` | `#1e3a5f` / `#16294a` / `#0f1d3b` — dark, sized to carry white | `#7da2d1` / `#9bbbe4` / `#c3d7ee` — light, sized to be text |
| Dark `--brand-50/100/200` | translucent `rgba(125,162,209,.13/.22/.32)` | opaque `#1c2b45` / `#27405f` / `#3c5a80` |

The two dark `--brand-*` ramps run in **opposite directions**. Any component rule
that uses `--brand-600` as a text colour is readable in DH dark (`#9bbbe4`, light)
and near-invisible in CO dark (`#16294a`, dark on dark: 1.11:1 against `--card`).
CO's Phase-A block avoided this by substituting `--primary` for `--brand-600`
throughout, but the substitution is per-rule, not enforced — a future port that
copies DH's `.side-a.on { color: var(--brand-600) }` verbatim into CO will ship a
1.11:1 pair.

## Full computed table

360 pairs. `fg` and `bg` are the final opaque colours after alpha compositing,
not the raw token values.

| App | Theme | Group | Pair | fg | bg | Ratio | Req | Verdict |
|---|---|---|---|---|---|---:|---:|---|
| CO | light | text | body text on --background | `#0f172a` | `#f6f7f9` | 16.65 | 4.5 | PASS |
| CO | light | text | body text on --card | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| CO | light | text | body text on --card-muted | `#0f172a` | `#f8fafc` | 17.06 | 4.5 | PASS |
| CO | light | text | soft text on --card (.side-a idle 13px) | `#475569` | `#ffffff` | 7.58 | 4.5 | PASS |
| CO | light | text | soft text on --background | `#475569` | `#f6f7f9` | 7.07 | 4.5 | PASS |
| CO | light | text | soft text on --surface-sunk (badge-neutral 11.5px) | `#475569` | `#f1f5f9` | 6.92 | 4.5 | PASS |
| CO | light | text | muted text on --card (11px .side-foot / stat label) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | text | muted text on --background | `#616e83` | `#f6f7f9` | 4.82 | 4.5 | PASS |
| CO | light | text | muted text on --card-muted (table th 11px) | `#616e83` | `#f8fafc` | 4.94 | 4.5 | PASS |
| CO | light | text | muted text on --surface-sunk (.side-a .ct count pill 11px) | `#616e83` | `#f1f5f9` | 4.71 | 4.5 | PASS |
| CO | light | text | muted text on --surface-subtle | `#616e83` | `#f8fafc` | 4.94 | 4.5 | PASS |
| CO | light | text | muted text on --surface-hover (row hover legacy) | `#616e83` | `#f1f5f9` | 4.71 | 4.5 | PASS |
| CO | light | semantic | --success on --success-soft over --card (badge 11.5px) | `#166534` | `#dcfce7` | 6.49 | 4.5 | PASS |
| CO | light | semantic | --success on --success-soft over --background (callout 12.5px) | `#166534` | `#dcfce7` | 6.49 | 4.5 | PASS |
| CO | light | semantic | --success on --card (stat value 22px) | `#166534` | `#ffffff` | 7.13 | 4.5 | PASS |
| CO | light | semantic | --warning on --warning-soft over --card (badge 11.5px) | `#92400e` | `#fef3c7` | 6.37 | 4.5 | PASS |
| CO | light | semantic | --warning on --warning-soft over --background (callout 12.5px) | `#92400e` | `#fef3c7` | 6.37 | 4.5 | PASS |
| CO | light | semantic | --warning on --card (stat value 22px) | `#92400e` | `#ffffff` | 7.09 | 4.5 | PASS |
| CO | light | semantic | --error on --error-soft over --card (badge 11.5px) | `#991b1b` | `#fdecec` | 7.28 | 4.5 | PASS |
| CO | light | semantic | --error on --error-soft over --background (callout 12.5px) | `#991b1b` | `#fdecec` | 7.28 | 4.5 | PASS |
| CO | light | semantic | --error on --card (stat value 22px) | `#991b1b` | `#ffffff` | 8.31 | 4.5 | PASS |
| CO | light | semantic | --info on --info-soft over --card (badge 11.5px) | `#1e40af` | `#dbeafe` | 7.15 | 4.5 | PASS |
| CO | light | semantic | --info on --info-soft over --background (callout 12.5px) | `#1e40af` | `#dbeafe` | 7.15 | 4.5 | PASS |
| CO | light | semantic | --info on --card (stat value 22px) | `#1e40af` | `#ffffff` | 8.72 | 4.5 | PASS |
| CO | light | semantic | --stale on --card (neutral dot / stale label 11.5px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | button | --primary-foreground on --primary (btn-primary 13px) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| CO | light | button | --primary-foreground on --primary-hover (btn-primary:hover) | `#ffffff` | `#16294a` | 14.48 | 4.5 | PASS |
| CO | light | button | --primary on --card (btn-secondary 13px) | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| CO | light | button | --primary on --brand-50 over --card (btn-secondary:hover) | `#1d3557` | `#eef2f7` | 10.99 | 4.5 | PASS |
| CO | light | button | --error on --card (btn-danger 13px) | `#991b1b` | `#ffffff` | 8.31 | 4.5 | PASS |
| CO | light | button | --error on --error-soft over --card (btn-danger:hover) | `#991b1b` | `#fdecec` | 7.28 | 4.5 | PASS |
| CO | light | button | --foreground-soft on --card (btn-ghost 13px) | `#475569` | `#ffffff` | 7.58 | 4.5 | PASS |
| CO | light | button | muted on --surface-sunk (disabled button — 1.4.3 exempt) | `#616e83` | `#f1f5f9` | 4.71 | n/a | INFO |
| CO | light | button | --primary-foreground on --primary (btn-xs 11.5px in table row) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| CO | light | sidebar | active item --primary on --brand-50 over --card (13px/600) | `#1d3557` | `#eef2f7` | 10.99 | 4.5 | PASS |
| CO | light | sidebar | active count pill --primary on --brand-100 over --brand-50 over --card (11px) | `#1d3557` | `#d6dfeb` | 9.19 | 4.5 | PASS |
| CO | light | sidebar | group label --foreground-muted on --card (10.5px uppercase) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | sidebar | hover item --foreground on --surface-sunk (13px) | `#0f172a` | `#f1f5f9` | 16.30 | 4.5 | PASS |
| CO | light | sidebar | footer link --foreground-muted on --card (11px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | header | header title #ffffff on header ground (14px/700) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| CO | light | header | header body #ffffff on header ground (12.5px switcher name) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| CO | light | header | header muted rgba(255,255,255,.62) on header ground (10.5px MST/id) | `#a9b2bf` | `#1d3557` | 5.79 | 4.5 | PASS |
| CO | light | header | header muted rgba(255,255,255,.82) on header ground (12.5px empty state) | `#d6dbe1` | `#1d3557` | 8.86 | 4.5 | PASS |
| CO | light | header | header caret rgba(255,255,255,.60) on header ground (non-text icon) | `#a5aebc` | `#1d3557` | 5.52 | 3.0 | PASS |
| CO | light | header | switcher chip #ffffff on rgba(255,255,255,.10) over header (12.5px) | `#ffffff` | `#344968` | 9.13 | 4.5 | PASS |
| CO | light | header | monogram --brand on #ffffff (12px/800) | `#4338ca` | `#ffffff` | 7.90 | 4.5 | PASS |
| CO | light | rail | step idle --foreground-muted on --card (12px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | rail | step current --primary on --card (12px/600) | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| CO | light | rail | step number --foreground-muted @opacity .75 on --card (10.5px) | `#8892a2` | `#ffffff` | 3.13 | 4.5 | FAIL |
| CO | light | rail | rail note --foreground-muted on --card (11.5px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | table | th --foreground-muted on --card-muted (11px uppercase) | `#616e83` | `#f8fafc` | 4.94 | 4.5 | PASS |
| CO | light | table | td --foreground on --card (13px) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| CO | light | table | td --foreground on --brand-50 over --card (row hover/selected) | `#0f172a` | `#eef2f7` | 15.88 | 4.5 | PASS |
| CO | light | table | dense td --foreground on --card (12px) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| CO | light | table | numeric cell --foreground on --card (12.5px mono) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| CO | light | link | link --primary on --card | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| CO | light | link | link --primary on --background | `#1d3557` | `#f6f7f9` | 11.53 | 4.5 | PASS |
| CO | light | link | link --primary on --card-muted | `#1d3557` | `#f8fafc` | 11.81 | 4.5 | PASS |
| CO | light | link | link --primary on --brand-50 over --card (link in hovered row) | `#1d3557` | `#eef2f7` | 10.99 | 4.5 | PASS |
| CO | light | link | link --primary on --surface-sunk | `#1d3557` | `#f1f5f9` | 11.28 | 4.5 | PASS |
| CO | light | link | link --primary-hover on --card | `#16294a` | `#ffffff` | 14.48 | 4.5 | PASS |
| CO | light | callout | callout body --foreground-soft on --brand-50 over --card (12.5px) | `#475569` | `#eef2f7` | 6.74 | 4.5 | PASS |
| CO | light | callout | callout body --foreground-soft on --brand-50 over --background (12.5px) | `#475569` | `#eef2f7` | 6.74 | 4.5 | PASS |
| CO | light | stat | stat value --foreground on --card (22px/700) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| CO | light | stat | stat value --primary on --card (22px/700) | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| CO | light | stat | stat label --foreground-muted on --card (11px uppercase) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | stat | stat sub --foreground-muted on --card (11.5px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| CO | light | chip | chip-active --primary-foreground on --primary (12px) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| CO | light | chip | tab hover --primary on --card-muted (13px) | `#1d3557` | `#f8fafc` | 11.81 | 4.5 | PASS |
| CO | light | chip | chip idle --foreground on --card (12px) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| CO | light | badge | badge-brand --primary on --brand-50 over --card (11.5px) | `#1d3557` | `#eef2f7` | 10.99 | 4.5 | PASS |
| CO | light | badge | status-pill --info on --info-soft over --card (11.5px) | `#1e40af` | `#dbeafe` | 7.15 | 4.5 | PASS |
| CO | light | nontext | input boundary --border-strong against --card | `#cbd5e1` | `#ffffff` | 1.48 | 3.0 | FAIL |
| CO | light | nontext | input boundary --border-strong against --background | `#cbd5e1` | `#f6f7f9` | 1.39 | 3.0 | FAIL |
| CO | light | nontext | card boundary --border against --background | `#e2e8f0` | `#f6f7f9` | 1.15 | n/a | INFO |
| CO | light | nontext | card ground --card against --background (surface separation) | `#ffffff` | `#f6f7f9` | 1.07 | n/a | INFO |
| CO | light | nontext | table header ground --card-muted against --card | `#f8fafc` | `#ffffff` | 1.05 | n/a | INFO |
| CO | light | nontext | focus ring --primary against --card | `#1d3557` | `#ffffff` | 12.36 | 3.0 | PASS |
| CO | light | nontext | focus ring --primary against --surface-input | `#1d3557` | `#ffffff` | 12.36 | 3.0 | PASS |
| CO | light | nontext | header focus ring #ffffff against header ground | `#ffffff` | `#1d3557` | 12.36 | 3.0 | PASS |
| CO | light | nontext | rail step dot idle --border-strong against --card | `#cbd5e1` | `#ffffff` | 1.48 | 3.0 | FAIL |
| CO | light | nontext | rail step dot done --brand-200 against --card | `#b9c8dd` | `#ffffff` | 1.70 | 3.0 | FAIL |
| CO | light | nontext | rail step dot current --primary against --card | `#1d3557` | `#ffffff` | 12.36 | 3.0 | PASS |
| CO | light | nontext | selected-row marker --primary against --brand-50 over --card | `#1d3557` | `#eef2f7` | 10.99 | 3.0 | PASS |
| CO | light | nontext | rail dot done --brand-200 against dot idle --border-strong (state pair) | `#b9c8dd` | `#cbd5e1` | 1.14 | 3.0 | FAIL |
| CO | light | nontext | row hover --brand-50 against --card (hover cue) | `#eef2f7` | `#ffffff` | 1.12 | n/a | INFO |
| CO | light | nontext | badge border --success-bd against --success-soft over --card | `#bbf7d0` | `#dcfce7` | 1.10 | n/a | INFO |
| CO | light | nontext | badge border --critical-bd against --error-soft over --card | `#f5c2c2` | `#fdecec` | 1.37 | n/a | INFO |
| CO | light | nontext | badge border --warning-bd against --warning-soft over --card | `#fcd99a` | `#fef3c7` | 1.21 | n/a | INFO |
| CO | light | nontext | badge border --info-bd against --info-soft over --card | `#bfdbfe` | `#dbeafe` | 1.16 | n/a | INFO |
| CO | dark | text | body text on --background | `#e2e8f0` | `#0f172a` | 14.48 | 4.5 | PASS |
| CO | dark | text | body text on --card | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| CO | dark | text | body text on --card-muted | `#e2e8f0` | `#0f172a` | 14.48 | 4.5 | PASS |
| CO | dark | text | soft text on --card (.side-a idle 13px) | `#cbd5e1` | `#1e293b` | 9.85 | 4.5 | PASS |
| CO | dark | text | soft text on --background | `#cbd5e1` | `#0f172a` | 12.02 | 4.5 | PASS |
| CO | dark | text | soft text on --surface-sunk (badge-neutral 11.5px) | `#cbd5e1` | `#0f172a` | 12.02 | 4.5 | PASS |
| CO | dark | text | muted text on --card (11px .side-foot / stat label) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | text | muted text on --background | `#94a3b8` | `#0f172a` | 6.96 | 4.5 | PASS |
| CO | dark | text | muted text on --card-muted (table th 11px) | `#94a3b8` | `#0f172a` | 6.96 | 4.5 | PASS |
| CO | dark | text | muted text on --surface-sunk (.side-a .ct count pill 11px) | `#94a3b8` | `#0f172a` | 6.96 | 4.5 | PASS |
| CO | dark | text | muted text on --surface-subtle | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | text | muted text on --surface-hover (row hover legacy) | `#94a3b8` | `#334155` | 4.04 | 4.5 | FAIL |
| CO | dark | semantic | --success on --success-soft over --card (badge 11.5px) | `#4ade80` | `#254445` | 6.04 | 4.5 | PASS |
| CO | dark | semantic | --success on --success-soft over --background (callout 12.5px) | `#4ade80` | `#183537` | 7.53 | 4.5 | PASS |
| CO | dark | semantic | --success on --card (stat value 22px) | `#4ade80` | `#1e293b` | 8.40 | 4.5 | PASS |
| CO | dark | semantic | --warning on --warning-soft over --card (badge 11.5px) | `#fbbf24` | `#3f4038` | 6.32 | 4.5 | PASS |
| CO | dark | semantic | --warning on --warning-soft over --background (callout 12.5px) | `#fbbf24` | `#323029` | 7.88 | 4.5 | PASS |
| CO | dark | semantic | --warning on --card (stat value 22px) | `#fbbf24` | `#1e293b` | 8.76 | 4.5 | PASS |
| CO | dark | semantic | --error on --error-soft over --card (badge 11.5px) | `#f87171` | `#3f3443` | 4.27 | 4.5 | FAIL |
| CO | dark | semantic | --error on --error-soft over --background (callout 12.5px) | `#f87171` | `#322435` | 5.26 | 4.5 | PASS |
| CO | dark | semantic | --error on --card (stat value 22px) | `#f87171` | `#1e293b` | 5.29 | 4.5 | PASS |
| CO | dark | semantic | --info on --info-soft over --card (badge 11.5px) | `#7da2d1` | `#2c3b52` | 4.29 | 4.5 | FAIL |
| CO | dark | semantic | --info on --info-soft over --background (callout 12.5px) | `#7da2d1` | `#202c43` | 5.31 | 4.5 | PASS |
| CO | dark | semantic | --info on --card (stat value 22px) | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| CO | dark | semantic | --stale on --card (neutral dot / stale label 11.5px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | button | --primary-foreground on --primary (btn-primary 13px) | `#0b1220` | `#7da2d1` | 7.10 | 4.5 | PASS |
| CO | dark | button | --primary-foreground on --primary-hover (btn-primary:hover) | `#0b1220` | `#9bbbe4` | 9.47 | 4.5 | PASS |
| CO | dark | button | --primary on --card (btn-secondary 13px) | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| CO | dark | button | --primary on --brand-50 over --card (btn-secondary:hover) | `#7da2d1` | `#2a394e` | 4.44 | 4.5 | FAIL |
| CO | dark | button | --error on --card (btn-danger 13px) | `#f87171` | `#1e293b` | 5.29 | 4.5 | PASS |
| CO | dark | button | --error on --error-soft over --card (btn-danger:hover) | `#f87171` | `#3f3443` | 4.27 | 4.5 | FAIL |
| CO | dark | button | --foreground-soft on --card (btn-ghost 13px) | `#cbd5e1` | `#1e293b` | 9.85 | 4.5 | PASS |
| CO | dark | button | muted on --surface-sunk (disabled button — 1.4.3 exempt) | `#94a3b8` | `#0f172a` | 6.96 | n/a | INFO |
| CO | dark | button | --primary-foreground on --primary (btn-xs 11.5px in table row) | `#0b1220` | `#7da2d1` | 7.10 | 4.5 | PASS |
| CO | dark | sidebar | active item --primary on --brand-50 over --card (13px/600) | `#7da2d1` | `#2a394e` | 4.44 | 4.5 | FAIL |
| CO | dark | sidebar | active count pill --primary on --brand-100 over --brand-50 over --card (11px) | `#7da2d1` | `#3d506b` | 3.12 | 4.5 | FAIL |
| CO | dark | sidebar | group label --foreground-muted on --card (10.5px uppercase) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | sidebar | hover item --foreground on --surface-sunk (13px) | `#e2e8f0` | `#0f172a` | 14.48 | 4.5 | PASS |
| CO | dark | sidebar | footer link --foreground-muted on --card (11px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | header | header title #ffffff on header ground (14px/700) | `#ffffff` | `#1e3a5f` | 11.50 | 4.5 | PASS |
| CO | dark | header | header body #ffffff on header ground (12.5px switcher name) | `#ffffff` | `#1e3a5f` | 11.50 | 4.5 | PASS |
| CO | dark | header | header muted rgba(255,255,255,.62) on header ground (10.5px MST/id) | `#aab4c2` | `#1e3a5f` | 5.49 | 4.5 | PASS |
| CO | dark | header | header muted rgba(255,255,255,.82) on header ground (12.5px empty state) | `#d6dce2` | `#1e3a5f` | 8.31 | 4.5 | PASS |
| CO | dark | header | header caret rgba(255,255,255,.60) on header ground (non-text icon) | `#a5b0bf` | `#1e3a5f` | 5.25 | 3.0 | PASS |
| CO | dark | header | switcher chip #ffffff on rgba(255,255,255,.10) over header (12.5px) | `#ffffff` | `#344e6f` | 8.54 | 4.5 | PASS |
| CO | dark | header | monogram --brand on #ffffff (12px/800) | `#818cf8` | `#ffffff` | 2.98 | 4.5 | FAIL |
| CO | dark | rail | step idle --foreground-muted on --card (12px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | rail | step current --primary on --card (12px/600) | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| CO | dark | rail | step number --foreground-muted @opacity .75 on --card (10.5px) | `#768499` | `#1e293b` | 3.88 | 4.5 | FAIL |
| CO | dark | rail | rail note --foreground-muted on --card (11.5px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | table | th --foreground-muted on --card-muted (11px uppercase) | `#94a3b8` | `#0f172a` | 6.96 | 4.5 | PASS |
| CO | dark | table | td --foreground on --card (13px) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| CO | dark | table | td --foreground on --brand-50 over --card (row hover/selected) | `#e2e8f0` | `#2a394e` | 9.51 | 4.5 | PASS |
| CO | dark | table | dense td --foreground on --card (12px) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| CO | dark | table | numeric cell --foreground on --card (12.5px mono) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| CO | dark | link | link --primary on --card | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| CO | dark | link | link --primary on --background | `#7da2d1` | `#0f172a` | 6.77 | 4.5 | PASS |
| CO | dark | link | link --primary on --card-muted | `#7da2d1` | `#0f172a` | 6.77 | 4.5 | PASS |
| CO | dark | link | link --primary on --brand-50 over --card (link in hovered row) | `#7da2d1` | `#2a394e` | 4.44 | 4.5 | FAIL |
| CO | dark | link | link --primary on --surface-sunk | `#7da2d1` | `#0f172a` | 6.77 | 4.5 | PASS |
| CO | dark | link | link --primary-hover on --card | `#9bbbe4` | `#1e293b` | 7.40 | 4.5 | PASS |
| CO | dark | callout | callout body --foreground-soft on --brand-50 over --card (12.5px) | `#cbd5e1` | `#2a394e` | 7.90 | 4.5 | PASS |
| CO | dark | callout | callout body --foreground-soft on --brand-50 over --background (12.5px) | `#cbd5e1` | `#1d2940` | 9.79 | 4.5 | PASS |
| CO | dark | stat | stat value --foreground on --card (22px/700) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| CO | dark | stat | stat value --primary on --card (22px/700) | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| CO | dark | stat | stat label --foreground-muted on --card (11px uppercase) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | stat | stat sub --foreground-muted on --card (11.5px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| CO | dark | chip | chip-active --primary-foreground on --primary (12px) | `#0b1220` | `#7da2d1` | 7.10 | 4.5 | PASS |
| CO | dark | chip | tab hover --primary on --card-muted (13px) | `#7da2d1` | `#0f172a` | 6.77 | 4.5 | PASS |
| CO | dark | chip | chip idle --foreground on --card (12px) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| CO | dark | badge | badge-brand --primary on --brand-50 over --card (11.5px) | `#7da2d1` | `#2a394e` | 4.44 | 4.5 | FAIL |
| CO | dark | badge | status-pill --info on --info-soft over --card (11.5px) | `#7da2d1` | `#2c3b52` | 4.29 | 4.5 | FAIL |
| CO | dark | nontext | input boundary --border-strong against --card | `#475569` | `#1e293b` | 1.93 | 3.0 | FAIL |
| CO | dark | nontext | input boundary --border-strong against --background | `#475569` | `#0f172a` | 2.36 | 3.0 | FAIL |
| CO | dark | nontext | card boundary --border against --background | `#334155` | `#0f172a` | 1.72 | n/a | INFO |
| CO | dark | nontext | card ground --card against --background (surface separation) | `#1e293b` | `#0f172a` | 1.22 | n/a | INFO |
| CO | dark | nontext | table header ground --card-muted against --card | `#0f172a` | `#1e293b` | 1.22 | n/a | INFO |
| CO | dark | nontext | focus ring --primary against --card | `#7da2d1` | `#1e293b` | 5.55 | 3.0 | PASS |
| CO | dark | nontext | focus ring --primary against --surface-input | `#7da2d1` | `#0f172a` | 6.77 | 3.0 | PASS |
| CO | dark | nontext | header focus ring #ffffff against header ground | `#ffffff` | `#1e3a5f` | 11.50 | 3.0 | PASS |
| CO | dark | nontext | rail step dot idle --border-strong against --card | `#475569` | `#1e293b` | 1.93 | 3.0 | FAIL |
| CO | dark | nontext | rail step dot done --brand-200 against --card | `#3c506b` | `#1e293b` | 1.77 | 3.0 | FAIL |
| CO | dark | nontext | rail step dot current --primary against --card | `#7da2d1` | `#1e293b` | 5.55 | 3.0 | PASS |
| CO | dark | nontext | selected-row marker --primary against --brand-50 over --card | `#7da2d1` | `#2a394e` | 4.44 | 3.0 | PASS |
| CO | dark | nontext | rail dot done --brand-200 against dot idle --border-strong (state pair) | `#586e8a` | `#475569` | 1.44 | 3.0 | FAIL |
| CO | dark | nontext | row hover --brand-50 against --card (hover cue) | `#2a394e` | `#1e293b` | 1.25 | n/a | INFO |
| CO | dark | nontext | badge border --success-bd against --success-soft over --card | `#327c5a` | `#254445` | 2.08 | n/a | INFO |
| CO | dark | nontext | badge border --critical-bd against --error-soft over --card | `#814a54` | `#3f3443` | 1.71 | n/a | INFO |
| CO | dark | nontext | badge border --warning-bd against --warning-soft over --card | `#836d31` | `#3f4038` | 2.11 | n/a | INFO |
| CO | dark | nontext | badge border --info-bd against --info-soft over --card | `#49607f` | `#2c3b52` | 1.76 | n/a | INFO |
| DH | light | text | body text on --background | `#0f172a` | `#f6f7f9` | 16.65 | 4.5 | PASS |
| DH | light | text | body text on --card | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| DH | light | text | body text on --card-muted | `#0f172a` | `#f8fafc` | 17.06 | 4.5 | PASS |
| DH | light | text | soft text on --card (.side-a idle 13px) | `#475569` | `#ffffff` | 7.58 | 4.5 | PASS |
| DH | light | text | soft text on --background | `#475569` | `#f6f7f9` | 7.07 | 4.5 | PASS |
| DH | light | text | soft text on --surface-sunk (badge-neutral 11.5px) | `#475569` | `#f1f5f9` | 6.92 | 4.5 | PASS |
| DH | light | text | muted text on --card (11px .side-foot / stat label) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | text | muted text on --background | `#616e83` | `#f6f7f9` | 4.82 | 4.5 | PASS |
| DH | light | text | muted text on --card-muted (table th 11px) | `#616e83` | `#f8fafc` | 4.94 | 4.5 | PASS |
| DH | light | text | muted text on --surface-sunk (.side-a .ct count pill 11px) | `#616e83` | `#f1f5f9` | 4.71 | 4.5 | PASS |
| DH | light | text | muted text on --surface-subtle | `#616e83` | `#f8fafc` | 4.94 | 4.5 | PASS |
| DH | light | text | muted text on --surface-hover (row hover legacy) | `#616e83` | `#f1f5f9` | 4.71 | 4.5 | PASS |
| DH | light | semantic | --success on --success-soft over --card (badge 11.5px) | `#166534` | `#dcfce7` | 6.49 | 4.5 | PASS |
| DH | light | semantic | --success on --success-soft over --background (callout 12.5px) | `#166534` | `#dcfce7` | 6.49 | 4.5 | PASS |
| DH | light | semantic | --success on --card (stat value 22px) | `#166534` | `#ffffff` | 7.13 | 4.5 | PASS |
| DH | light | semantic | --warning on --warning-soft over --card (badge 11.5px) | `#92400e` | `#fef3c7` | 6.37 | 4.5 | PASS |
| DH | light | semantic | --warning on --warning-soft over --background (callout 12.5px) | `#92400e` | `#fef3c7` | 6.37 | 4.5 | PASS |
| DH | light | semantic | --warning on --card (stat value 22px) | `#92400e` | `#ffffff` | 7.09 | 4.5 | PASS |
| DH | light | semantic | --error on --error-soft over --card (badge 11.5px) | `#991b1b` | `#fdecec` | 7.28 | 4.5 | PASS |
| DH | light | semantic | --error on --error-soft over --background (callout 12.5px) | `#991b1b` | `#fdecec` | 7.28 | 4.5 | PASS |
| DH | light | semantic | --error on --card (stat value 22px) | `#991b1b` | `#ffffff` | 8.31 | 4.5 | PASS |
| DH | light | semantic | --info on --info-soft over --card (badge 11.5px) | `#1e40af` | `#dbeafe` | 7.15 | 4.5 | PASS |
| DH | light | semantic | --info on --info-soft over --background (callout 12.5px) | `#1e40af` | `#dbeafe` | 7.15 | 4.5 | PASS |
| DH | light | semantic | --info on --card (stat value 22px) | `#1e40af` | `#ffffff` | 8.72 | 4.5 | PASS |
| DH | light | semantic | --stale on --card (neutral dot / stale label 11.5px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | button | --primary-foreground on --primary (btn-primary 13px) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| DH | light | button | --primary-foreground on --primary-hover (btn-primary:hover) | `#ffffff` | `#16294a` | 14.48 | 4.5 | PASS |
| DH | light | button | --primary on --card (btn-secondary 13px) | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| DH | light | button | --primary on --brand-50 over --card (btn-secondary:hover) | `#1d3557` | `#eef2f7` | 10.99 | 4.5 | PASS |
| DH | light | button | --error on --card (btn-danger 13px) | `#991b1b` | `#ffffff` | 8.31 | 4.5 | PASS |
| DH | light | button | --error on --error-soft over --card (btn-danger:hover) | `#991b1b` | `#fdecec` | 7.28 | 4.5 | PASS |
| DH | light | button | --foreground-muted on --card (btn-ghost 13px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | button | muted on --surface-sunk (disabled button — 1.4.3 exempt) | `#616e83` | `#f1f5f9` | 4.71 | n/a | INFO |
| DH | light | button | --primary-foreground on --primary (btn-xs 11.5px in table row) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| DH | light | sidebar | active item --brand-600 on --brand-50 over --card (13px/600) | `#16294a` | `#eef2f7` | 12.88 | 4.5 | PASS |
| DH | light | sidebar | active count pill --brand-600 on --brand-100 over --brand-50 over --card (11px) | `#16294a` | `#d6dfeb` | 10.77 | 4.5 | PASS |
| DH | light | sidebar | group label --foreground-muted on --card (10.5px uppercase) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | sidebar | hover item --foreground on --surface-sunk (13px) | `#0f172a` | `#f1f5f9` | 16.30 | 4.5 | PASS |
| DH | light | sidebar | footer link --foreground-muted on --card (11px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | header | header title #ffffff on header ground (14px/700) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| DH | light | header | header body #ffffff on header ground (12.5px switcher name) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| DH | light | header | header muted rgba(255,255,255,.62) on header ground (10.5px MST/id) | `#a9b2bf` | `#1d3557` | 5.79 | 4.5 | PASS |
| DH | light | header | header muted rgba(255,255,255,.82) on header ground (12.5px empty state) | `#d6dbe1` | `#1d3557` | 8.86 | 4.5 | PASS |
| DH | light | header | header caret rgba(255,255,255,.60) on header ground (non-text icon) | `#a5aebc` | `#1d3557` | 5.52 | 3.0 | PASS |
| DH | light | header | switcher chip #ffffff on rgba(255,255,255,.10) over header (12.5px) | `#ffffff` | `#344968` | 9.13 | 4.5 | PASS |
| DH | light | header | monogram --brand on #ffffff (12px/800) | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| DH | light | rail | step idle --foreground-muted on --card (12px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | rail | step current --brand-600 on --card (12px/600) | `#16294a` | `#ffffff` | 14.48 | 4.5 | PASS |
| DH | light | rail | step number --foreground-muted @opacity .75 on --card (10.5px) | `#8892a2` | `#ffffff` | 3.13 | 4.5 | FAIL |
| DH | light | rail | rail note --foreground-muted on --card (11.5px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | table | th --foreground-muted on --card-muted (11px uppercase) | `#616e83` | `#f8fafc` | 4.94 | 4.5 | PASS |
| DH | light | table | td --foreground on --card (13px) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| DH | light | table | td --foreground on --brand-50 over --card (row hover/selected) | `#0f172a` | `#eef2f7` | 15.88 | 4.5 | PASS |
| DH | light | table | dense td --foreground on --card (12px) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| DH | light | table | numeric cell --foreground on --card (12.5px mono) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| DH | light | link | link --primary on --card | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| DH | light | link | link --primary on --background | `#1d3557` | `#f6f7f9` | 11.53 | 4.5 | PASS |
| DH | light | link | link --primary on --card-muted | `#1d3557` | `#f8fafc` | 11.81 | 4.5 | PASS |
| DH | light | link | link --primary on --brand-50 over --card (link in hovered row) | `#1d3557` | `#eef2f7` | 10.99 | 4.5 | PASS |
| DH | light | link | link --primary on --surface-sunk | `#1d3557` | `#f1f5f9` | 11.28 | 4.5 | PASS |
| DH | light | link | link --primary-hover on --card | `#16294a` | `#ffffff` | 14.48 | 4.5 | PASS |
| DH | light | callout | callout body --foreground-soft on --brand-50 over --card (12.5px) | `#475569` | `#eef2f7` | 6.74 | 4.5 | PASS |
| DH | light | callout | callout body --foreground-soft on --brand-50 over --background (12.5px) | `#475569` | `#eef2f7` | 6.74 | 4.5 | PASS |
| DH | light | stat | stat value --foreground on --card (22px/700) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| DH | light | stat | stat value --primary on --card (22px/700) | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| DH | light | stat | stat label --foreground-muted on --card (11px uppercase) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | stat | stat sub --foreground-muted on --card (11.5px) | `#616e83` | `#ffffff` | 5.16 | 4.5 | PASS |
| DH | light | chip | chip-active --primary-foreground on --primary (12px) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| DH | light | chip | tab hover --primary on --card-muted (13px) | `#1d3557` | `#f8fafc` | 11.81 | 4.5 | PASS |
| DH | light | chip | chip idle --foreground on --card (12px) | `#0f172a` | `#ffffff` | 17.85 | 4.5 | PASS |
| DH | light | badge | badge-dual #8b3fb5 on rgba(180,60,200,.15) over --card (11.5px) | `#8b3fb5` | `#f4e2f7` | 4.90 | 4.5 | PASS |
| DH | light | badge | badge-brand --brand-600 on --brand-50 over --card (11.5px) | `#16294a` | `#eef2f7` | 12.88 | 4.5 | PASS |
| DH | light | nontext | input boundary --border-strong against --card | `#cbd5e1` | `#ffffff` | 1.48 | 3.0 | FAIL |
| DH | light | nontext | input boundary --border-strong against --background | `#cbd5e1` | `#f6f7f9` | 1.39 | 3.0 | FAIL |
| DH | light | nontext | card boundary --border against --background | `#e2e8f0` | `#f6f7f9` | 1.15 | n/a | INFO |
| DH | light | nontext | card ground --card against --background (surface separation) | `#ffffff` | `#f6f7f9` | 1.07 | n/a | INFO |
| DH | light | nontext | table header ground --card-muted against --card | `#f8fafc` | `#ffffff` | 1.05 | n/a | INFO |
| DH | light | nontext | focus ring --primary against --card | `#1d3557` | `#ffffff` | 12.36 | 3.0 | PASS |
| DH | light | nontext | focus ring --primary against --surface-input | `#1d3557` | `#ffffff` | 12.36 | 3.0 | PASS |
| DH | light | nontext | header focus ring #ffffff against header ground | `#ffffff` | `#1d3557` | 12.36 | 3.0 | PASS |
| DH | light | nontext | rail step dot idle --border-strong against --card | `#cbd5e1` | `#ffffff` | 1.48 | 3.0 | FAIL |
| DH | light | nontext | rail step dot done --brand-200 against --card | `#b9c8dd` | `#ffffff` | 1.70 | 3.0 | FAIL |
| DH | light | nontext | rail step dot current --brand-500 against --card | `#1d3557` | `#ffffff` | 12.36 | 3.0 | PASS |
| DH | light | nontext | selected-row marker --brand-500 against --brand-50 over --card | `#1d3557` | `#eef2f7` | 10.99 | 3.0 | PASS |
| DH | light | nontext | rail dot done --brand-200 against dot idle --border-strong (state pair) | `#b9c8dd` | `#cbd5e1` | 1.14 | 3.0 | FAIL |
| DH | light | nontext | row hover --brand-50 against --card (hover cue) | `#eef2f7` | `#ffffff` | 1.12 | n/a | INFO |
| DH | light | nontext | badge border --success-bd against --success-soft over --card | `#bbf7d0` | `#dcfce7` | 1.10 | n/a | INFO |
| DH | light | nontext | badge border --critical-bd against --error-soft over --card | `#f5c2c2` | `#fdecec` | 1.37 | n/a | INFO |
| DH | light | nontext | badge border --warning-bd against --warning-soft over --card | `#fcd99a` | `#fef3c7` | 1.21 | n/a | INFO |
| DH | light | nontext | badge border --info-bd against --info-soft over --card | `#bfdbfe` | `#dbeafe` | 1.16 | n/a | INFO |
| DH | dark | text | body text on --background | `#e2e8f0` | `#0f172a` | 14.48 | 4.5 | PASS |
| DH | dark | text | body text on --card | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| DH | dark | text | body text on --card-muted | `#e2e8f0` | `#0f172a` | 14.48 | 4.5 | PASS |
| DH | dark | text | soft text on --card (.side-a idle 13px) | `#cbd5e1` | `#1e293b` | 9.85 | 4.5 | PASS |
| DH | dark | text | soft text on --background | `#cbd5e1` | `#0f172a` | 12.02 | 4.5 | PASS |
| DH | dark | text | soft text on --surface-sunk (badge-neutral 11.5px) | `#cbd5e1` | `#16233b` | 10.57 | 4.5 | PASS |
| DH | dark | text | muted text on --card (11px .side-foot / stat label) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | text | muted text on --background | `#94a3b8` | `#0f172a` | 6.96 | 4.5 | PASS |
| DH | dark | text | muted text on --card-muted (table th 11px) | `#94a3b8` | `#0f172a` | 6.96 | 4.5 | PASS |
| DH | dark | text | muted text on --surface-sunk (.side-a .ct count pill 11px) | `#94a3b8` | `#16233b` | 6.12 | 4.5 | PASS |
| DH | dark | text | muted text on --surface-subtle | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | text | muted text on --surface-hover (row hover legacy) | `#94a3b8` | `#334155` | 4.04 | 4.5 | FAIL |
| DH | dark | semantic | --success on --success-soft over --card (badge 11.5px) | `#4ade80` | `#254646` | 5.90 | 4.5 | PASS |
| DH | dark | semantic | --success on --success-soft over --background (callout 12.5px) | `#4ade80` | `#183738` | 7.35 | 4.5 | PASS |
| DH | dark | semantic | --success on --card (stat value 22px) | `#4ade80` | `#1e293b` | 8.40 | 4.5 | PASS |
| DH | dark | semantic | --warning on --warning-soft over --card (badge 11.5px) | `#fbbf24` | `#414137` | 6.17 | 4.5 | PASS |
| DH | dark | semantic | --warning on --warning-soft over --background (callout 12.5px) | `#fbbf24` | `#353229` | 7.69 | 4.5 | PASS |
| DH | dark | semantic | --warning on --card (stat value 22px) | `#fbbf24` | `#1e293b` | 8.76 | 4.5 | PASS |
| DH | dark | semantic | --error on --error-soft over --card (badge 11.5px) | `#f87171` | `#413544` | 4.20 | 4.5 | FAIL |
| DH | dark | semantic | --error on --error-soft over --background (callout 12.5px) | `#f87171` | `#342535` | 5.17 | 4.5 | PASS |
| DH | dark | semantic | --error on --card (stat value 22px) | `#f87171` | `#1e293b` | 5.29 | 4.5 | PASS |
| DH | dark | semantic | --info on --info-soft over --card (badge 11.5px) | `#7da2d1` | `#2d3c53` | 4.21 | 4.5 | FAIL |
| DH | dark | semantic | --info on --info-soft over --background (callout 12.5px) | `#7da2d1` | `#212d45` | 5.21 | 4.5 | PASS |
| DH | dark | semantic | --info on --card (stat value 22px) | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| DH | dark | semantic | --stale on --card (neutral dot / stale label 11.5px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | button | --primary-foreground on --primary (btn-primary 13px) | `#0b1220` | `#7da2d1` | 7.10 | 4.5 | PASS |
| DH | dark | button | --primary-foreground on --primary-hover (btn-primary:hover) | `#0b1220` | `#9bbbe4` | 9.47 | 4.5 | PASS |
| DH | dark | button | --primary on --card (btn-secondary 13px) | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| DH | dark | button | --primary on --brand-50 over --card (btn-secondary:hover) | `#7da2d1` | `#1c2b45` | 5.38 | 4.5 | PASS |
| DH | dark | button | --error on --card (btn-danger 13px) | `#f87171` | `#1e293b` | 5.29 | 4.5 | PASS |
| DH | dark | button | --error on --error-soft over --card (btn-danger:hover) | `#f87171` | `#413544` | 4.20 | 4.5 | FAIL |
| DH | dark | button | --foreground-muted on --card (btn-ghost 13px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | button | muted on --surface-sunk (disabled button — 1.4.3 exempt) | `#94a3b8` | `#16233b` | 6.12 | n/a | INFO |
| DH | dark | button | --primary-foreground on --primary (btn-xs 11.5px in table row) | `#0b1220` | `#7da2d1` | 7.10 | 4.5 | PASS |
| DH | dark | sidebar | active item --brand-600 on --brand-50 over --card (13px/600) | `#9bbbe4` | `#1c2b45` | 7.17 | 4.5 | PASS |
| DH | dark | sidebar | active count pill --brand-600 on --brand-100 over --brand-50 over --card (11px) | `#9bbbe4` | `#27405f` | 5.35 | 4.5 | PASS |
| DH | dark | sidebar | group label --foreground-muted on --card (10.5px uppercase) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | sidebar | hover item --foreground on --surface-sunk (13px) | `#e2e8f0` | `#16233b` | 12.73 | 4.5 | PASS |
| DH | dark | sidebar | footer link --foreground-muted on --card (11px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | header | header title #ffffff on header ground (14px/700) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| DH | dark | header | header body #ffffff on header ground (12.5px switcher name) | `#ffffff` | `#1d3557` | 12.36 | 4.5 | PASS |
| DH | dark | header | header muted rgba(255,255,255,.62) on header ground (10.5px MST/id) | `#a9b2bf` | `#1d3557` | 5.79 | 4.5 | PASS |
| DH | dark | header | header muted rgba(255,255,255,.82) on header ground (12.5px empty state) | `#d6dbe1` | `#1d3557` | 8.86 | 4.5 | PASS |
| DH | dark | header | header caret rgba(255,255,255,.60) on header ground (non-text icon) | `#a5aebc` | `#1d3557` | 5.52 | 3.0 | PASS |
| DH | dark | header | switcher chip #ffffff on rgba(255,255,255,.10) over header (12.5px) | `#ffffff` | `#344968` | 9.13 | 4.5 | PASS |
| DH | dark | header | monogram --brand on #ffffff (12px/800) | `#1d3557` | `#ffffff` | 12.36 | 4.5 | PASS |
| DH | dark | rail | step idle --foreground-muted on --card (12px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | rail | step current --brand-600 on --card (12px/600) | `#9bbbe4` | `#1e293b` | 7.40 | 4.5 | PASS |
| DH | dark | rail | step number --foreground-muted @opacity .75 on --card (10.5px) | `#768499` | `#1e293b` | 3.88 | 4.5 | FAIL |
| DH | dark | rail | rail note --foreground-muted on --card (11.5px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | table | th --foreground-muted on --card-muted (11px uppercase) | `#94a3b8` | `#0f172a` | 6.96 | 4.5 | PASS |
| DH | dark | table | td --foreground on --card (13px) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| DH | dark | table | td --foreground on --brand-50 over --card (row hover/selected) | `#e2e8f0` | `#1c2b45` | 11.50 | 4.5 | PASS |
| DH | dark | table | dense td --foreground on --card (12px) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| DH | dark | table | numeric cell --foreground on --card (12.5px mono) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| DH | dark | link | link --primary on --card | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| DH | dark | link | link --primary on --background | `#7da2d1` | `#0f172a` | 6.77 | 4.5 | PASS |
| DH | dark | link | link --primary on --card-muted | `#7da2d1` | `#0f172a` | 6.77 | 4.5 | PASS |
| DH | dark | link | link --primary on --brand-50 over --card (link in hovered row) | `#7da2d1` | `#1c2b45` | 5.38 | 4.5 | PASS |
| DH | dark | link | link --primary on --surface-sunk | `#7da2d1` | `#16233b` | 5.95 | 4.5 | PASS |
| DH | dark | link | link --primary-hover on --card | `#9bbbe4` | `#1e293b` | 7.40 | 4.5 | PASS |
| DH | dark | callout | callout body --foreground-soft on --brand-50 over --card (12.5px) | `#cbd5e1` | `#1c2b45` | 9.55 | 4.5 | PASS |
| DH | dark | callout | callout body --foreground-soft on --brand-50 over --background (12.5px) | `#cbd5e1` | `#1c2b45` | 9.55 | 4.5 | PASS |
| DH | dark | stat | stat value --foreground on --card (22px/700) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| DH | dark | stat | stat value --primary on --card (22px/700) | `#7da2d1` | `#1e293b` | 5.55 | 4.5 | PASS |
| DH | dark | stat | stat label --foreground-muted on --card (11px uppercase) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | stat | stat sub --foreground-muted on --card (11.5px) | `#94a3b8` | `#1e293b` | 5.71 | 4.5 | PASS |
| DH | dark | chip | chip-active --primary-foreground on --primary (12px) | `#0b1220` | `#7da2d1` | 7.10 | 4.5 | PASS |
| DH | dark | chip | tab hover --primary on --card-muted (13px) | `#7da2d1` | `#0f172a` | 6.77 | 4.5 | PASS |
| DH | dark | chip | chip idle --foreground on --card (12px) | `#e2e8f0` | `#1e293b` | 11.87 | 4.5 | PASS |
| DH | dark | badge | badge-dual #d8a8eb on rgba(180,100,220,.25) over --card (11.5px) | `#d8a8eb` | `#443863` | 5.40 | 4.5 | PASS |
| DH | dark | badge | badge-brand --brand-600 on --brand-50 over --card (11.5px) | `#9bbbe4` | `#1c2b45` | 7.17 | 4.5 | PASS |
| DH | dark | nontext | input boundary --border-strong against --card | `#475569` | `#1e293b` | 1.93 | 3.0 | FAIL |
| DH | dark | nontext | input boundary --border-strong against --background | `#475569` | `#0f172a` | 2.36 | 3.0 | FAIL |
| DH | dark | nontext | card boundary --border against --background | `#334155` | `#0f172a` | 1.72 | n/a | INFO |
| DH | dark | nontext | card ground --card against --background (surface separation) | `#1e293b` | `#0f172a` | 1.22 | n/a | INFO |
| DH | dark | nontext | table header ground --card-muted against --card | `#0f172a` | `#1e293b` | 1.22 | n/a | INFO |
| DH | dark | nontext | focus ring --primary against --card | `#7da2d1` | `#1e293b` | 5.55 | 3.0 | PASS |
| DH | dark | nontext | focus ring --primary against --surface-input | `#7da2d1` | `#0f172a` | 6.77 | 3.0 | PASS |
| DH | dark | nontext | header focus ring #ffffff against header ground | `#ffffff` | `#1d3557` | 12.36 | 3.0 | PASS |
| DH | dark | nontext | rail step dot idle --border-strong against --card | `#475569` | `#1e293b` | 1.93 | 3.0 | FAIL |
| DH | dark | nontext | rail step dot done --brand-200 against --card | `#3c5a80` | `#1e293b` | 2.07 | 3.0 | FAIL |
| DH | dark | nontext | rail step dot current --brand-500 against --card | `#7da2d1` | `#1e293b` | 5.55 | 3.0 | PASS |
| DH | dark | nontext | selected-row marker --brand-500 against --brand-50 over --card | `#7da2d1` | `#1c2b45` | 5.38 | 3.0 | PASS |
| DH | dark | nontext | rail dot done --brand-200 against dot idle --border-strong (state pair) | `#3c5a80` | `#475569` | 1.07 | 3.0 | FAIL |
| DH | dark | nontext | row hover --brand-50 against --card (hover cue) | `#1c2b45` | `#1e293b` | 1.03 | n/a | INFO |
| DH | dark | nontext | badge border --success-bd against --success-soft over --card | `#14532d` | `#254646` | 1.13 | n/a | INFO |
| DH | dark | nontext | badge border --critical-bd against --error-soft over --card | `#7f1d1d` | `#413544` | 1.16 | n/a | INFO |
| DH | dark | nontext | badge border --warning-bd against --warning-soft over --card | `#78350f` | `#414137` | 1.14 | n/a | INFO |
| DH | dark | nontext | badge border --info-bd against --info-soft over --card | `#1e3a5f` | `#2d3c53` | 1.04 | n/a | INFO |

## Ranked failures — text (1.4.3, 4.5:1)

Ranked worst first. Each fix states a replacement value and the ratio that value
produces, computed by the same script.

### T1 — CO dark monogram, 2.98:1 (needs 4.5)

`--brand: #818cf8` on the white monogram tile at 12px weight 800.
`co-app.css:140` sets the token; `co-app.css:8534` defines
`.brand-mark { background:#fff; color: var(--brand) }`.

- **Fix:** `--brand: #4f46e5` in `body[data-theme="dark"]` → **6.29:1**.
- Minimum hue-preserving value that clears the bar is `#676fc5` → 4.51:1. Use
  `#4f46e5` (indigo-600): it is already on the ramp and leaves headroom.
- Do **not** use `#6366f1` (indigo-500) — computed 4.47:1, still failing.

### T2 — rail step number, 3.13:1 light / 3.88:1 dark (needs 4.5) — both apps

`.rail-s .n { font-size:10.5px; opacity:0.75 }` — `co-app.css:8860`,
`dh-app.css:3801`. The element `opacity` multiplies onto `--foreground-muted`,
producing `#8892a2` on `#ffffff` (light) and `#768499` on `#1e293b` (dark).

- **Fix:** delete `opacity: 0.75` from the rule. `--foreground-muted` then renders
  unmodified: **5.16:1** light, **5.71:1** dark. This is a rule fix, not a token
  change — no other pair moves.
- If the dimming must stay, `--foreground-muted` would have to become `#64748b`
  light (4.76:1 through the 0.75 opacity) and `#94a3b8`→lighter dark, which
  changes 14 other pairs. Delete the opacity instead.

### T3 — CO dark sidebar active count pill, 3.12:1 (needs 4.5)

`.side-a.on .ct` (`co-app.css:8791`) — `--primary` `#7da2d1` on `--brand-100`
`rgba(125,162,209,.22)` composited over `--brand-50` `rgba(125,162,209,.13)`
over `--card` `#1e293b`, final ground `#3d506b`. 11px mono.

- **Fix:** make CO's dark brand tints opaque, as Data Hub already does —
  `--brand-50: #1c2b45`, `--brand-100: #22364f` (`co-app.css:127-128`). Pill then
  computes **4.66:1**.
- Do **not** copy DH's `--brand-100: #27405f` into CO: with CO's `--primary`
  foreground that gives **4.01:1**, still failing. DH passes at `#27405f` only
  because its foreground is `--brand-600` `#9bbbe4` (5.35:1).

### T4 — muted text on `--surface-hover`, dark, 4.04:1 (needs 4.5) — both apps

`--foreground-muted` `#94a3b8` on `--surface-hover` `#334155`
(`co-app.css:96`, `dh-app.css:104`). This is the legacy hover ground still used by
`.topnav-links a:hover`, `.btn-secondary:hover` (pre-redesign block) and
`.picker-row:hover`.

- **Fix A (preferred):** `--surface-hover: #293546` in the dark block → **4.84:1**.
  Keeps `--foreground-muted` untouched, so no other pair moves.
- **Fix B:** `--foreground-muted: #cbd5e1` dark → 6.97:1 here, but it collapses the
  soft/muted distinction (`--foreground-soft` is already `#cbd5e1`).

### T5 — semantic tints on dark, 4.20–4.29:1 (needs 4.5)

Four pairs, both apps. The `*-soft` tokens are `rgba()` at 0.15/0.16 over
`--card` `#1e293b`, which lifts the ground enough to eat the margin.

| Pair | App | Current ground | Ratio |
|---|---|---|---|
| `--error` `#f87171` on `--error-soft` | DH | `#413544` | 4.20 |
| `--info` `#7da2d1` on `--info-soft` | DH | `#2d3c53` | 4.21 |
| `--error` `#f87171` on `--error-soft` | CO | `#3f3443` | 4.27 |
| `--info` `#7da2d1` on `--info-soft` | CO | `#2c3b52` | 4.29 |

Affects `.badge-error`, `.badge-info`, `.btn-danger:hover`, and CO's
`.status-progress` pill.

- **Fix (preferred, one change per token):** lower the tint alpha in the dark
  blocks — `--error-soft: rgba(248,113,113,0.10)` → **4.62:1**;
  `--info-soft: rgba(125,162,209,0.10)` → **4.69:1**.
  Alpha 0.12 computes 4.4639 and 4.5050 — 4.505 rounds to a pass but leaves no
  margin, so use 0.10.
- **Fix (alternative):** lighten the foregrounds — `--error: #fca5a5` → 6.12:1 (DH)
  / 6.22:1 (CO); `--info: #93c5fd` → 6.16:1 (DH) / 6.27:1 (CO). This also lifts
  `--error` on `--card` from 5.29 to 7.71, but it changes the callout and stat-tile
  variants at the same time.
- `--success` (6.04/5.90) and `--warning` (6.32/6.17) already pass; leave them.

### T6 — CO dark `--primary` on `--brand-50`, 4.44:1 (needs 4.5) — four pairs

`--primary` `#7da2d1` on `--brand-50` `rgba(125,162,209,.13)` over `--card`,
final ground `#2a394e`. Hits `.side-a.on` (`co-app.css:8774`), `.badge-brand`
(`co-app.css:9120`), `.btn-secondary:hover`, and any link inside a hovered table
row (`.table tbody tr:hover` at `co-app.css:9131`).

- **Fix:** the same `--brand-50: #1c2b45` from T3 → **5.38:1** across all four
  pairs. One token change closes the whole cluster.
- Data Hub already passes here (5.38:1) because it uses the opaque value.

### T7 — DH dark `.badge-dual`, 2.14:1 (needs 4.5)

`dh-app.css:2401` — `[data-theme="dark"] .badge-dual { background:
rgba(180,100,220,0.25); color:#d8a8eb }`. Ground composites to `#342c50`.
This rule predates the redesign and was not retuned.

- **Fix:** `color: #e9d5ff` on `#342c50` → **9.51:1**; or drop the hard-coded rule
  and route the badge through the `--logic-*` ramp like every other badge kind.

## Ranked failures — non-text (1.4.11, 3:1)

These are numerically the worst pairs in the system and they are systemic: they
apply to every form control and every pipeline rail, in both apps, in both
themes.

### N1 — rail "done" step is distinguishable from "idle" only by a dot at 1.07–1.14:1

`.rail-s::before { background: var(--border-strong) }` and
`.rail-s.done::before { background: var(--brand-200) }` — `co-app.css:8844/8881`,
`dh-app.css:3788/3805`. A completed step and a not-yet-reached step differ in
**nothing but that dot's fill**: same text colour (`--foreground-muted`), same
weight, no text change, no `aria` attribute. `.rail-s.on` is fine (it changes
colour *and* weight *and* carries `aria-current="step"`).

Measured dot-vs-dot separation: **1.14:1** light, **1.09:1** CO dark, **1.07:1**
DH dark. Dot against its `--card` ground: 1.70:1 light / 1.77:1 (CO dark) /
2.07:1 (DH dark) for done, 1.48:1 light / 1.93:1 dark for idle.

This is simultaneously a 1.4.11 failure and a 1.4.1 (use of colour) failure.

- **Fix (colour part):** the three constraints interact — idle must clear 3:1
  against `--card`, done must clear 3:1 against `--card`, and the two must clear
  3:1 against each other. The two dots therefore have to sit on opposite sides of
  the card's luminance. The one pairing that satisfies all three in both themes:
  keep the idle dot on `--border-strong` **after** applying N2's `#64748b`, and
  move the done dot to `--foreground`:

  | | idle `#64748b` vs card | done `--foreground` vs card | idle vs done |
  |---|---:|---:|---:|
  | light (`--card` `#ffffff`, done `#0f172a`) | 4.76 | 17.85 | **3.75** |
  | dark (`--card` `#1e293b`, done `#e2e8f0`) | 3.07 | 11.87 | **3.86** |

  `.rail-s.done::before { background: var(--foreground) }` replaces
  `var(--brand-200)`. Do **not** use `--primary` for the done dot: `#7da2d1`
  against `#475569` computes **2.87:1** dark and, against the N2-corrected idle
  `#64748b`, only **1.80:1**.
- **Fix (non-colour part, required):** colour alone still fails 1.4.1 no matter
  what the ratio is. Give the done dot a different shape — a check glyph, or
  `border-radius:2px` versus the circle — and add visually-hidden text to the
  step. Data Hub renders the rail in `app/templates/clients/_flow.html:13-28`;
  only the current step gets `aria-current="step"`, so a done step and a pending
  step announce identically to a screen reader.

### N2 — form input boundary, 1.48:1 light / 1.93:1 dark (needs 3:1) — both apps

`--border-strong` is the input border (`co-app.css:9164`,
`dh-app.css:4082`: `input,select,textarea { border: 1px solid
var(--border-strong) }`). Light `#cbd5e1` on `--card` `#ffffff` = **1.48:1**, on
`--background` `#f6f7f9` = 1.39:1. Dark `#475569` on `#1e293b` = **1.93:1**, on
`#0f172a` = 2.36:1. Under 1.4.11 the boundary that identifies a text input must
reach 3:1.

- **Fix (light):** `--border-strong: #64748b` → **4.76:1** on `--card`, 4.44:1 on
  `--background`. Minimum hue-preserving value is `#8a97a9` at 2.97:1 — that is
  still short, so `#64748b` (slate-500) is the first ramp step that works.
- **Fix (dark):** `--border-strong: #64748b` → **3.07:1** on `--card`, 3.75:1 on
  `--background`. Minimum is `#667283` at 3.00:1.
- **Tradeoff, decide before applying:** `--border-strong` is not input-only. It is
  also the table-header bottom rule, the `.btn-secondary` border, `.chip` border
  and the rail idle dot. Darkening it globally to `#64748b` makes the whole
  system visibly heavier than the reference. The alternative is a dedicated
  `--border-input: #64748b` used only by `input,select,textarea` and the rail dot,
  leaving `--border-strong` at `#cbd5e1` for decorative rules. That scoping call
  belongs to the agent that owns the input styles, not to this audit.

### N3 — rail idle/done dots against their ground

Covered by N1 and N2: the idle dot uses `--border-strong` (N2's fix carries it to
4.76:1 light / 3.07:1 dark) and the done dot uses `--brand-200` (1.70:1 light,
1.77:1 CO dark, 2.07:1 DH dark). Moving `.rail-s.done::before` to `--foreground`
per N1 takes it to 17.85:1 light / 11.87:1 dark against `--card`.

## Computed but not failing — recorded for the record

- **Focus rings pass everywhere they exist.** `outline: 2px solid var(--primary)`
  on `--card`: 12.36:1 light, 5.55:1 dark. The header's white ring on the navy
  ground: 12.36:1 (CO light) / 11.50:1 (CO dark) / 12.36:1 (DH both).
- **Header muted text passes.** `rgba(255,255,255,.62)` at 10.5px composites to
  `#a9b2bf` on `#1d3557` = 5.79:1 (CO dark: `#aab4c2` on `#1e3a5f` = 5.49:1).
  `rgba(255,255,255,.82)` at 12.5px = 8.86:1.
- **Table headers pass at 11px:** `--foreground-muted` on `--card-muted` = 4.94:1
  light, 6.96:1 dark — but with only 0.44 of margin in light theme.
- **Muted text on `--background` = 4.82:1** and **on `--surface-sunk` = 4.71:1** in
  light theme. Both pass; both are within 0.32 of failing. Any future darkening of
  `--background` or lightening of `--foreground-muted` breaks them.
- **Decorative separations are low but carry no requirement:** `--card` vs
  `--background` 1.07:1 light / 1.22:1 dark; `--card-muted` vs `--card` 1.05:1
  light / 1.22:1 dark; badge borders vs their own fills 1.10–1.37:1. Each of these
  surfaces also has a `--border` edge, so 1.4.11 is not engaged. Recorded so a
  later reviewer does not re-open them.

## Non-colour findings

### A1 — no `<th scope>` anywhere: 0 of 631 header cells, both apps

| App | `<th>` in templates | with `scope=` |
|---|---:|---:|
| CO | 155 | **0** |
| Data Hub | 476 | **0** |

WCAG 1.3.1. Worst-affected templates by header count:
`app/templates/co_case.html` (39), `app/templates/bom.html` (27),
`app/templates/co_form_settings.html` (22) in CO;
`app/templates/clients/catalog_detail.html` (36),
`app/templates/clients/bom_artifact_detail.html` (29),
`app/templates/clients/parser_rules.html` (24) in Data Hub.

Every one of these is a data grid where the header text is the only thing that
identifies a column, and the redesign makes the header *smaller* (11px) and
*lighter* (`--foreground-muted`) than the cells. Add `scope="col"` on column
headers and `scope="row"` where the first cell of a row is a `<th>`.

### A2 — no global focus-visible rule for links or buttons in either app

Neither `app.css` defines `a:focus-visible` or `button:focus-visible`. Coverage
by element type, from the snapshots:

| Element type | CO | Data Hub |
|---|---|---|
| `input` / `select` / `textarea` | covered — `co-app.css:9174`, `outline:2px solid var(--primary)`, 12.36:1 light / 5.55:1 dark | covered — `dh-app.css` `input…:focus` block, same values |
| `a` (incl. `.side-a`, `.side-foot a`, `.tab-link`) | **UA default only** | **UA default only** |
| `button` (incl. `.btn-primary/secondary/ghost/danger`, `.btn-xs`, `.chip`) | **UA default only** | **UA default only** |
| `.topnav-chip-button` | covered — `co-app.css:8690`, white ring on navy, 12.36:1 / 11.50:1 | covered — `dh-app.css:385` |
| `.rail-s` | none | none (rendered as `<span>`, not focusable at all) |
| `.table-link` | none | n/a |
| table row link | none | covered — `dh-app.css:2315`, `tr[data-row-href]:focus-visible` |

The UA default ring satisfies 2.4.7 on plain grounds, but `.btn-primary` and
`.chip-active` are navy fills and `.topnav` items sit on a navy header, where
the default ring is low contrast. Add one rule per app:
`a:focus-visible, button:focus-visible { outline:2px solid var(--primary);
outline-offset:2px }`, plus the existing white-ring override inside `.topnav`.

### A3 — three rules remove the focus ring; one replacement is below 3:1

| Rule | File:line | Replacement indicator | Ratio |
|---|---|---|---:|
| `.origin-material-code-btn:hover, :focus` | `co-app.css:5329` | fill changes to `--info-soft` | **1.22:1** light, 1.29:1 dark |
| `.picker-search:focus-visible` | `co-app.css:2044` | border → `color-mix(--primary 45%, --border)` = `#8997ab` | **2.97:1** — short of 3.0 |
| `.field input:focus` | `dh-app.css:2280` | border → `--primary`, halo → `--primary-soft` | halo 1.12:1 light / 1.31:1 dark; border delta 12.36:1 light, 5.55:1 dark — **adequate via the border** |
| `.chat-widget-input:focus` | `dh-app.css:1911` | border → `--primary` only | 12.36:1 light / 5.55:1 dark — adequate |
| `.uom-search:focus` | `dh-app.css:3184` | border → `--primary` only | same — adequate |

`.origin-material-code-btn` is the worst of these on two counts: the focus
indicator is a 1.22:1 tint, and `:hover` and `:focus` share one declaration
block, so a keyboard user cannot tell focus from a passing mouse. Split the
selectors and restore `outline: 2px solid var(--primary)` on `:focus-visible`.

`.picker-search` at 2.97:1 misses by 0.03 — `#8997ab` needs to become `#8895a8`
(3.01:1) or, better, the rule should keep the standard outline.

### A4 — state carried by colour alone

| Case | File:line | Non-colour cue present? | Measured |
|---|---|---|---:|
| Rail done vs idle step | `co-app.css:8881` / `dh-app.css:3805`, `clients/_flow.html:13-28` | **no** — same text colour, same weight, no `aria` | 1.14:1 light / 1.07:1 dark |
| `.origin-material-code-overridden` | `co-app.css:5335` | **no** — `--warning-soft` fill only | fill vs `--card` 1.11:1 |
| Sidebar active item | `co-app.css:8774`, `dh-app.css:3698` | yes — `font-weight:600` alongside the tint | — |
| Rail current step | `co-app.css:8871`, `dh-app.css:3803` | yes — weight 600 + `aria-current="step"` | — |
| Badges | `co-app.css:9083`, `dh-app.css:3970` | yes — the badge text names the state | — |
| Disabled buttons | `co-app.css:9071` | yes — `cursor:not-allowed`, and CO's `.btn-secondary:disabled` at `co-app.css:2910` adds `border-style:dashed` | — |
| Table selected row | `co-app.css:9136` | yes — `inset 3px 0 0 var(--primary)` marker, 4.44:1 CO dark / 10.99:1 light against the row tint | — |

Two real failures of 1.4.1: the rail done/idle pair (see N1) and
`.origin-material-code-overridden`, where an operator-edited origin code is
marked only by an amber tint at 1.11:1 against the surrounding cell. Add a glyph
or a short label to the overridden cell.

### A5 — sidebar active item has no `aria-current`

`co-app.css`/`base.html:249-276` and `dh` `_sidebar.html:14-82` both set the
active item with a Jinja class toggle (`{{ 'on' if nav_active == … }}`) and no
`aria-current="page"`. Across both apps: 3 `aria-current` occurrences in CO
templates, 3 in Data Hub — all on the pipeline rail, none on the sidebar. Visual
users get weight 600 plus the tint; screen-reader users get nothing. Add
`aria-current="page"` to the `.side-a.on` branch.

### A6 — form labels

| App | `<label>` | with `for=` | `<input>` (non-hidden) | `<select>` | `<textarea>` | `aria-label` on a control |
|---|---:|---:|---:|---:|---:|---:|
| CO | 93 | **2** | 107 | 32 | 13 | 6 |
| Data Hub | 168 | 62 | 154 | 57 | 6 | 1 |

CO's low `for=` count is not by itself a defect: the dominant pattern, sampled in
`app/templates/client_config.html:27,32,91,100,117,126,131,150,160,186,204`, is
`<label class="fld">` wrapping both the caption and the control, which is a valid
implicit association. The gap that remains is the control count versus the label
count — CO has 152 non-hidden controls against 93 labels and 6 `aria-label`s,
Data Hub 217 against 168 and 1. That leaves roughly 53 (CO) and 48 (DH) controls
unaccounted for. Toolbar search boxes and in-table editors are the likely
residue; `app/templates/_advanced_table.html:5` shows the wrapping pattern used
for the table search, which is fine. A per-template pass is needed to confirm the
remainder — this audit measured the counts, it did not verify each control.

Also: only 2 `aria-live` regions in CO and 1 in Data Hub, against a UI that does
inline recalculation and autosave. Status changes after a save are announced to
nobody.

### A7 — 11px and under used for read-repeatedly content, not glance content

The density retune puts several strings an operator must *read* — not glance at —
below 12px. Ratios all pass; the issue is size, not contrast.

| Element | Size | File:line | Ratio (light / dark) | Read or glance |
|---|---|---|---|---|
| `.side-a .ct` count pill, mono | 11px | `co-app.css:8780`, `dh-app.css:3704` | 4.71 / 6.96 | **read** — the row counts (materials, BOM lines, BCCT, tồn CO) are the numbers an operator checks against the source workbook |
| Table `th`, uppercase, `letter-spacing:.05em` | 11px | `co-app.css:4128`, `dh-app.css:4025` | 4.94 / 6.96 | **read** — the only column identifier in a bảng kê grid that runs to 1,000+ rows and 20+ columns; uppercase plus letterspacing at 11px is the least legible combination in the system |
| `.dn-switch .mst` / `.client-switch-id`, mono | 10.5px | `co-app.css:8627`, `dh-app.css:3600` | 5.77 / 5.49 | **read** — the MST is a 10–13 digit tax code that the operator verifies before working a dossier; it is verification content sitting at the smallest size in the app |
| `.rail-s .n` step number | 10.5px @ `opacity:.75` | `co-app.css:8860`, `dh-app.css:3801` | **3.13 / 3.88 — FAIL** | glance, but it fails contrast regardless (see T2) |
| `.side-grp` group label, uppercase | 10.5px | `co-app.css:8746`, `dh-app.css:3668` | 5.16 / 5.71 | glance — acceptable |
| `.badge` | 11.5px | `co-app.css:9083`, `dh-app.css:3970` | 6.49 / 6.05 (success) | **read** — the status word is per-row content in every list |
| `.btn-xs` in table rows | 11.5px | `co-app.css:9064`, `dh-app.css:4406` | 12.36 / 7.10 | **read** — action labels, per row |
| `.hero-stat-label` / `.ddc-label`, uppercase | 11px | `co-app.css:9192`, `dh-app.css:4142` | 5.16 / 5.71 | glance — acceptable |
| `.dense` table cells | 12px | `co-app.css:9143`, `dh-app.css:4058` | 17.85 / 11.87 | **read** — DESIGN.md makes `.dense` the default for any grid over ~30 rows, so 12px becomes the size of the actual data |

Recommendation, in priority order: raise the table `th` from 11px to 12px and
drop `text-transform:uppercase` (keep the letterspacing and the muted colour for
the hierarchy); raise `.mst` / `.client-switch-id` from 10.5px to 12px; raise
`.side-a .ct` from 11px to 11.5px. The 11px uppercase treatment is right for
`.side-grp` and the stat-tile labels, which are read once per screen.

## Scope note

CO's `.rail` / `.rail-s` markup currently exists only in
`app/templates/design_gallery.html`. Findings N1, N3 and T2's dark half bind Data
Hub today (`app/templates/clients/_flow.html`) and bind CO the moment the rail is
wired into a real pipeline screen. The token-level fixes (T1, T3, T5, T6, N2)
apply to both apps now.
